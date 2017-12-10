FROM python:3.6
ADD . /opt/airpurifier-prometheus
WORKDIR /opt/airpurifier-prometheus
RUN pip install --editable .
CMD ["airpurifier_exporter"]