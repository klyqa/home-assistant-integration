#!/bin/bash

mkdir -p ~/.ha_config
bash -xc install_to_ha.sh ~/.ha_config
docker-compose up -d
# docker exec -it homeassistant_klyqa python -m pip install -r /config/custom_components/klyqa/requirements.txt