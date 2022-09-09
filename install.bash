#!/bin/bash
# wget -O - https://raw.githubusercontent.com/klyqa/home-assistant-integration/main/install.bash | bash -
set -e

all_yes=$1

RED_COLOR='\033[0;31m'
GREEN_COLOR='\033[0;32m'
GREEN_YELLOW='\033[1;33m'
NO_COLOR='\033[0m'

declare haPath
declare -a paths=(
    "$PWD"
    "$PWD/config"
    "/config"
    "$HOME/.homeassistant"
    "/usr/share/hassio/homeassistant"
)

function info () { echo -e "${GREEN_COLOR}INFO: $1${NO_COLOR}";}
function warn () { echo -e "${GREEN_YELLOW}WARN: $1${NO_COLOR}";}
function error () { echo -e "${RED_COLOR}ERROR: $1${NO_COLOR}"; if [ "$2" != "false" ]; then exit 1;fi; }

# function checkRequirement () {
#     if [ -z "$(command -v "$1")" ]; then
#         error "'$1' is not installed"
#     fi
# }

# checkRequirement "wget"
# checkRequirement "unzip"

info "Trying to find the correct directory..."
for path in "${paths[@]}"; do
    if [ -n "$haPath" ]; then
        break
    fi

    if [ -f "$path/home-assistant.log" ]; then
        haPath="$path"
    else
        if [ -d "$path/.storage" ] && [ -f "$path/configuration.yaml" ]; then
            haPath="$path"
        fi
    fi
done

if [ -n "$haPath" ]; then
    info "Found Home Assistant configuration directory at '$haPath'"
    cd "$haPath" || error "Could not change path to $haPath"
    if [ ! -d "$haPath/custom_components" ]; then
        info "Creating custom_components directory..."
        mkdir "$haPath/custom_components"
    fi

    info "Changing to the custom_components directory..."
    cd "$haPath/custom_components" || error "Could not change path to $haPath/custom_components"

    if [ -d "$haPath/custom_components/klyqa" ]; then
        warn "Klyqa Integration Installation found, delete and update it [Y/n]? "
        read -n1 x; echo
        if [ ! "$all_yes" = "y" ] && [ ! "$x" = "y" ] && [ ! "$x" = "Y" ]; then
            echo "Stop."
            exit 0
        fi
        rm -R "$haPath/custom_components/klyqa"
    fi

    info "Cloning Klyqa Home Assistant Integration..."
    git clone https://github.com/klyqa/home-assistant-integration klyqa

    info "Initialize submodules.."
    (cd klyqa && git submodule update --init --recursive)

    if [ -f "$haPath/configuration.yaml" ]; then
        printf "Add example klyqa config to configuration.yaml (connect your klyqa account in homeassistant) [Y/n]? "
        read -n1 x; echo
        if [ "$all_yes" = "y" ] || [ "$x" = "y" ] || [ "$x" = "Y" ]; then
            cat <<EOF >> $haPath/configuration.yaml
# light:
#   - platform: klyqa
#     username: your_username@yourprovider.com
#     password: !secret your_password_from_secret.yaml
#     sync_rooms: True
#     polling: True
#     scan_interval: 120
EOF
        fi
    else
        printf "Cannot find configuration.yaml. Print Klyqa example configuration in the terminal [Y/n]? "
        read -n1 x; echo
        if [ "$all_yes" = "y" ] || [ "$x" = "y" ] || [ "$x" = "Y" ]; then
            cat <<EOF
light:
  - platform: klyqa
    username: your_username@yourprovider.com
    password: !secret your_password_from_secret.yaml
    sync_rooms: True
    polling: True
    scan_interval: 120
EOF
        fi
    fi

    info "Remember to restart Home Assistant before you configure it"

else
    echo
    error "Could not find the directory for Home Assistant" false
    echo "Manually change the directory to the root of your Home Assistant configuration"
    echo "With the user that is running Home Assistant"
    echo "and run the script again"
    exit 1
fi
