#!/bin/bash
set -e

#
# Install or update Home Assistant Klyqa integration from git repository.
#

config_path=$1
branch=$2
[ -z "${branch}" ] && branch=main


int_path=${config_path}/custom_components/klyqa
mkdir -p ${config_path}/custom_components

if [ -d "${int_path}" ]; then
  if cd "${int_path}" && git status 2>/dev/null >&2; then
    git fetch --all
    git pull
  else
    read -p "Found Klyqa integration in path ${int_path} but not as git a repository. Delete it and clone it there? [Y/n] " -n1 x
    [ -n "${x}" ] && ( [ ! "${x}" = "y" ] || [ ! "${x}" = "Y" ] ) && exit 0
    rm -rf "${int_path}"
    git clone -b ${branch} https://github.com/klyqa/home-assistant-integration ${int_path}
  fi
fi
python -m pip install -r ${int_path}/requirements.txt
echo
echo "Klyqa integration (${int_path}) up-to-date."