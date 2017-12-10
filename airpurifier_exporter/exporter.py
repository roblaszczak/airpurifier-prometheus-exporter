import logging
import os
from distutils.util import strtobool
from time import sleep, time

import forecastio
import miio
import prometheus_client
import requests
import zeroconf
from aqi.algos.epa import AQI, Decimal, ROUND_HALF_EVEN, POLLUTANT_PM25
from miio import AirPurifier
from miio.airpurifier import OperationMode, AirPurifierStatus
from miio.discovery import Listener, pretty_token
from prometheus_client import Gauge

METRICS_PREFIX = 'airpurifier_'

log_level = logging.DEBUG if strtobool(os.environ.get('AIRPURIFIER_DEBUG', 'false')) else logging.INFO
logging.basicConfig(level=log_level)
logger = logging.getLogger('airpurifier-prometheus')


def main():
    logger.info('Starting')

    ip = os.environ.get('AIRPURIFIER_IP')
    token = os.environ.get('AIRPURIFIER_TOKEN')

    if not ip or not token:
        logger.info('No AIRPURIFIER_IP and AIRPURIFIER_TOKEN provided, starting discovery')

        ip, token = auto_discover()
        if ip is None or token is None:
            raise Exception("Do device found")

    values = [
        Value('aqi', 'Air Quality Index', lambda status: status.aqi, Gauge),
        Value('pm25_micrograms_per_m3', 'PM 2.5', lambda status: aqi_to_pm25(status.aqi), Gauge),
        Value('humidity_percent', 'Humidity', lambda status: status.humidity, Gauge),
        Value('temperature_celsius', 'Temperature', lambda status: status.temperature, Gauge),
        Value('filter_life_remaining_percent', 'Filter life remaining', lambda status: status.filter_life_remaining,
              Gauge),
        Value('filter_used_seconds', 'Filter hours used', lambda status: status.filter_hours_used * 60 * 60, Gauge),
        Value('use_time_seconds', 'Use time', lambda status: status.use_time, Gauge),
        Value('motor_speed_rpm', 'Motor speed', lambda status: status.motor_speed, Gauge),
        Value('power_on', 'Power', lambda status: 1 if status.power == 'on' else 0, Gauge),
        ModeValue('mode', 'Mode', None, Gauge, ['mode']),
    ]

    airly_api_key = os.environ.get('AIRPURIFIER_AIRLY_API_KEY')
    forecastio_api_key = os.environ.get('AIRPURIFIER_FORECASTIO_API_KEY')

    location_lat = os.environ.get('AIRPURIFIER_LOCATION_LAT')
    location_lng = os.environ.get('AIRPURIFIER_LOCATION_LNG')

    add_outside_pm25(airly_api_key, location_lat, location_lng, values)
    add_outside_climate(forecastio_api_key, location_lat, location_lng, values)

    prometheus_port = int(os.environ.get('AIRPURIFIER_EXPORTER_PORT', 8000))
    logger.info('Starting Prometheus exporter on port %d', (prometheus_port))
    prometheus_client.start_http_server(prometheus_port)

    while True:
        logger.info('Updating values')

        try:
            ap = AirPurifier(ip=ip, token=token)
            status = ap.status()

            for value in values:
                value.update_metric(status)
        except:
            logger.exception('Error during updating value')
            pass

        logger.info('Values updated')
        sleep(os.environ.get('AIRPURIFIER_VALUES_UPDATE_INTERVAL', 5))


class Value():
    def __init__(self, prom_metric_name, prom_metric_label, get_value_func, metric_type, prom_labels=None):
        self.get_value_func = get_value_func

        self.stat = metric_type(METRICS_PREFIX + prom_metric_name, prom_metric_label, prom_labels)

    def update_metric(self, status: AirPurifierStatus):
        self.stat.set(self.get_value_func(status))


class ModeValue(Value):
    def update_metric(self, status: AirPurifierStatus):
        self.stat.labels(mode='auto').set(int(status.mode == OperationMode.Auto))
        self.stat.labels(mode='silent').set(int(status.mode == OperationMode.Silent))
        self.stat.labels(mode='favorite').set(int(status.mode == OperationMode.Favorite))
        self.stat.labels(mode='idle').set(int(status.mode == OperationMode.Idle))


class OutsidePm2Value(Value):
    last_update = None

    def __init__(self, prom_metric_name, prom_metric_label, apikey, lat, lng):
        super().__init__(prom_metric_name, prom_metric_label, None, Gauge)
        self.apikey = apikey
        self.lat = lat
        self.lng = lng

    def update_metric(self, status: AirPurifierStatus):
        if self.last_update is None or time() - self.last_update >= 120:
            self.stat.set(self.get_outside_pm25())
            self.last_update = time()

    def get_outside_pm25(self):
        r = requests.get(
            'https://airapi.airly.eu/v1/nearestSensor/measurements?latitude=%s&longitude=%s&maxDistance=10000' % (
                self.lat, self.lng),
            headers={'apikey': self.apikey}
        )

        return r.json()['pm25']


class OutsideClimateValue(Value):
    last_update = None

    def __init__(self, temperature_stat_name, humidity_stat_name, api_key, lat, lng):
        self.temperature_stat = Gauge(METRICS_PREFIX + temperature_stat_name, 'Outside temperature')
        self.humidity_stat = Gauge(METRICS_PREFIX + humidity_stat_name, 'Outside humidity')
        self.api_key = api_key
        self.lat = lat
        self.lng = lng

    def update_metric(self, status: AirPurifierStatus):
        if self.last_update is None or time() - self.last_update >= 120:
            forecast = forecastio.load_forecast(self.api_key, self.lat, self.lng)
            current = forecast.currently()

            self.temperature_stat.set(current.temperature)
            self.humidity_stat.set(current.humidity * 100)

            self.last_update = time()


def aqi_to_pm25(aqi_value):
    aqi_idx = None
    aqilo, aqihi = None, None

    for key, range in enumerate(AQI.piecewise['aqi']):
        if range[0] <= aqi_value <= range[1]:
            aqi_idx = key
            (aqilo, aqihi) = range
            break

    if aqi_idx is None:
        raise Exception("invalid aqi")

    (pm25lo, pm25hi) = AQI.piecewise['bp'][POLLUTANT_PM25][aqi_idx]
    pm25val = (((Decimal(aqi_value) - aqilo) / (aqihi - aqilo)) * (pm25hi - pm25lo)) + pm25lo

    return pm25val.quantize(Decimal('1.'), rounding=ROUND_HALF_EVEN)


def auto_discover():
    listener = Listener()
    browser = zeroconf.ServiceBrowser(zeroconf.Zeroconf(), "_miio._udp.local.", listener)

    logger.info('Discovering device')

    sleep_time = 0.1
    timeout = 10
    retries_left = timeout / sleep_time

    while retries_left > 0:
        sleep(sleep_time)

        for device in listener.found_devices.values():
            if isinstance(device, miio.airpurifier.AirPurifier):
                logger.info('Found device, ip: %(ip)s, %(token)s',
                            {'ip': device.ip, 'token': pretty_token(device.token)})

                browser.cancel()
                return device.ip, pretty_token(device.token)

        retries_left -= 1

    logger.error('No supported device found, found devices: %s', (listener.found_devices))
    browser.cancel()
    return None, None


def add_outside_climate(forecastio_api_key, location_lat, location_lng, values):
    if forecastio_api_key:
        values.append(
            OutsideClimateValue(
                'outside_temperature_celsius',
                'outside_humidity_percent',
                api_key=forecastio_api_key,
                lat=location_lat,
                lng=location_lng,
            ))
    else:
        logger.warn('Outside climate stats are disabled. AIRPURIFIER_FORECASTIO_API_KEY, AIRPURIFIER_LOCATION_LAT and '
                    'AIRPURIFIER_LOCATION_LNG are required.')


def add_outside_pm25(airly_api_key, location_lat, location_lng, values):
    if airly_api_key and location_lat and location_lng:
        values.append(OutsidePm2Value(
            'outside_pm25_micrograms_per_m3',
            'Outside PM 2.5',
            apikey=airly_api_key,
            lat=location_lat,
            lng=location_lng,
        ))
    else:
        logger.warn('Outside PM2.5 stats is disabled. AIRPURIFIER_AIRLY_API_KEY, AIRPURIFIER_LOCATION_LAT and '
                    'AIRPURIFIER_LOCATION_LNG are required.')


if __name__ == '__main__':
    main()
