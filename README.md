# Xiaomi Air Purifier 2 Prometheus Exporter

![Dashboard preview](/docs/dashboard-preview.png)

Some crazy idea made after too much of yerba.

Project is in alpha stage, so there is a big chance that it should not work :)

## Running in docker

Just run

    docker-compose up

Do daemonize run

    docker-compose up -d

Then you can visit [http://localhost:3000/](http://localhost:3000/) and configure Prometheus data source (http://localhost:9090)
and import dashboard [dashboard.json](/dashboard.json).

I would also recommend to check Configuring section to set up Forecat.io, Airly API keys
and set your locations coords to get information about outside conditions.

## Configuring

Available env vars:

```
AIRPURIFIER_DEBUG=false
AIRPURIFIER_EXPORTER_PORT=8000
AIRPURIFIER_FORECASTIO_API_KEY= # you can get API Key here: https://darksky.net/dev/
AIRPURIFIER_LOCATION_LAT=
AIRPURIFIER_LOCATION_LNG=
AIRPURIFIER_AIRLY_API_KEY= # you can get API Key here: https://developer.airly.eu/
```

## License

This project is licensed under the MIT License - see the [LICENSE.md](LICENSE.md) file for details
