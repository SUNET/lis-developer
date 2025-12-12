FROM apache/airflow:latest

# Python dependencies
COPY requirements.txt /python-dependencies/requirements.txt
# Wheel files
COPY *.whl /python-dependencies/

USER airflow

RUN pip install --no-cache-dir -r /python-dependencies/requirements.txt
RUN find /python-dependencies -name "*.whl" | xargs -r pip install --no-cache-dir
