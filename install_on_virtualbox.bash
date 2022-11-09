#!/bin/bash

# parameters:
# 1. path to vdi virtual disk file
# 2. [optional] qemu nbd device path to use for mount

set -e

vdi=$1
dev=$2
[ -n "$dev" ] || dev=/dev/nbd0

sudo apt-get install qemu qemu-utils git coreutils
if [ -z "$vdi" ]; then
  link=https://github.com/home-assistant/operating-system/releases/download/9.3/haos_ova-9.3.vdi.zip
  wget -q --method=HEAD $link || {
  echo "The link $link for the vdi ist not up-to-date anymore."
  echo "Please search for the installation of home assistant with virtualbox, download the vdi virtual disk file and parse it to this script."
  exit 1
  }
  wget -O haos_ova-9.3.vdi.zip $link || { echo "Error during downloading the vdi $link file."; exit 1; }
  unzip haos_ova-9.3.vdi.zip || { echo "Error during unzipping the vdi haos_ova-9.3.vdi.zip file."; exit 1; }
  vdi=haos_ova-9.3.vdi
fi

sudo rmmod nbd
sudo modprobe nbd max_part=16

sudo qemu-nbd -c $dev $vdi

tmp=$(mktemp -d)
sudo mount ${dev}p8 $tmp

(cd $tmp/supervisor/homeassistant/mkdir -p custom_components/ && cd custom_components
rm -rf klyqa
git clone https://github.com/klyqa/home-assistant-integration klyqa
)

umount $tmp
sudo qemu-nbd -d ${dev}

echo "Please look on the home assistant virtualbox installation configuration to set the right settings for the virtualbox."
echo "The link to look might be: https://www.home-assistant.io/installation/linux"