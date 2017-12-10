from setuptools import setup, find_packages

setup(
    name='airpurifier-prometheus',
    author='Robert Laszczak',
    license='MIT',
    packages=find_packages(exclude=['contrib', 'docs', 'tests']),
    install_requires=[
        'python-forecastio==1.3.5',
        'prometheus_client==0.0.21',
        'requests==2.11.1',
        'python-aqi==0.5.1',
        'python-miio==0.3.2',

        'construct<=2.8.16', # dependency of python-miio, for some reasaon 2.8.17 is not working
    ],
    entry_points={
        'console_scripts': [
            'airpurifier_exporter=airpurifier_exporter.exporter:main',
        ],
    },
)
