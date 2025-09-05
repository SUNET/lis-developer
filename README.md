# lis-developer
Developer repository for the LIS project



## Configuration

### 1. Docker

* Create the `lis-network` docker network
```
$ docker network create lis-network
```




### 2. CISO Assistant

1. Run `ciso-docker-compose.yml`

2. Create an user account in CISO Assistant (the first one is usually the administrator account)
```
docker compose exec ciso-backend poetry run python manage.py createsuperuser
```

3. Add the username and password of the user just created in `ciso-dispatcher` service environment variables of `ciso-docker-compose.yml`:
```
    - USER_EMAIL=email
    - USER_PASSWORD=1234
```

`ciso-dispatcher` does not need to authenticate to Redpanda in the development environment, so there no need to configure the `KAFKA_USERNAME` and `KAFKA_PASSWORD` environment variables.



### 3. Redpanda

1. Run `redpanda-docker-compose.yml`

2. Create topics in Redpanda console:
    * observation
    * errors

The topic names should match the environment variables in the `ciso-dispatcher` service in the `ciso-docker-compose.yml`.
```
    - ERRORS_TOPIC=errors
    - OBSERVATION_TOPIC=observation
```

If the CISO `dispatcher` service is configure correctly you can see the `my-group` consumer group in the `consumers` tab under the `observation` topic.

There might be needed to configure an ACL to allow the `my-group` consumer group to consume from the `observation` topic.

The docker compose configuration is taken from the Redpanda documentation.


### 4. Apache Airflow

1. Run `apache-airflow-docker-compose.yaml`

The docker compose configuration is taken from the Airflow documentation.


## Run

Run the docker compose files in order:

1. `redpanda-docker-compose.yml`
2. `ciso-docker-compose.yml`

Apache Airflow can run in any order because it is not integrated with the other services yet.


## Usage
You can reach the web interface of each service at the following URLs:
* CISO Assistant: https://localhost:8443/
* Redpanda console: http://localhost:8088/
    * No login required
    * By default it runs a `enterprise` license. But it is not required and when it expires it will run a `community` license.
* Apache airflow: http://localhost:8080/
    * The web login is `airflow` and the password is `airflow`.

To test that the CISO Assistant + CISO dispatcher + Redpanda are working one should:
1. Create an Audit in the CISO Assistant
2. Set a Reference ID in the Audit
3. Add a JSON configured correcly in the `observation` topic in Redpanda.

The JSON configuration is documented in https://github.com/intuitem/ciso-assistant-community/tree/main/dispatcher 

An JSON example is https://github.com/intuitem/ciso-assistant-community/blob/main/dispatcher/samples/messages/update_requirement_assessment.json

JSON schemas for the 3 types of messages are in https://github.com/intuitem/ciso-assistant-community/tree/main/dispatcher/data/schemas/commands



## Notes

The S3 Storage service is not yet in the project, but we are considering MinIO.

For more information check the LIS wiki, for example under `Technology` page.
