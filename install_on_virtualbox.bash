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

error=false

(cd $tmp/supervisor/homeassistant && mkdir -p custom_components
    rm -rf custom_components/klyqa
    printf "Do you want to install Klyqa Home Assistant Integration directly or managed via Home Assistant Community Store"
    printf " (HACS, you get update hints on new releases on the Klyqa Integration from the Github repository with HACS) [k/H] ? "
    read x
    if [ "$x" = "k"]; then
        cd custom_components
        git clone https://github.com/klyqa/home-assistant-integration klyqa
        echo
        echo "Installation of Klyqa integration finished."
        echo "When you have started the virtualbox Home Assistant Machine and went to http://homeassistant.local:8123/ and setted up your Home Assistant,"
        echo "please go to Configuration > Devices & Services > + Add Integration > enter \"Klyqa\" and add the Integration."
    elif [ "$x" = "H" ] || [ -z "$x" ]; then
        wget -O - https://get.hacs.xyz | bash - || { echo "Error during HACS installation."; exit 1; }
        echo
        echo "Installation of HACS finished."
        echo "When you have started the virtualbox Home Assistant Machine and went to http://homeassistant.local:8123/ and setted up your Home Assistant,"
        echo "please go to Configuration > Devices & Services > + Add Integration > enter \"HACS\" and add the Integration."
        echo "You should have a HACS tab in the left bar then, click there, go to Integrations and on the right top hit the three dot Menu and click on add"
        echo " custom repository. There enter: \"https://github.com/klyqa/home-assistant-integration\" and Category \"Integration\"."
        echo "If it's added to the listed repositories, you close the dialog and click on the right bottom on search and download from repositories."
        echo "Search there for Klyqa and add it. Restart Home Assistant."
        echo "After installation you should be able to add the klyqa integration in Configuration > Devices & Services > + Add Integration > \"Klyqa\"."

    fi
) || error=true

umount $tmp
sudo qemu-nbd -d ${dev}

if ! $error; then
  echo
  echo "Please look on the home assistant virtualbox installation configuration to set the right settings for the virtualbox machine."
  echo "The link to look might be: https://www.home-assistant.io/installation/linux"
fi

