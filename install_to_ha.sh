#!/bin/bash

config_path=$1
mkdir -p ${config_path}/custom_components
if [ -d "${config_path}/custom_components/klyqa" ]; then
  if cd "${config_path}/custom_components/klyqa" && git status 2>/dev/null >&2; then
    git fetch --all
  else
    rm -rf "${config_path}/custom_components/klyqa"
    git clone -b development https://github.com/klyqa/home-assistant-integration ${config_path}/custom_components/klyqa
    python -m pip install -r ${config_path}/custom_components/klyqa/requirements.txt
  fi
fi