# Install Home Assistant in Virtualbox with the Klyqa Integration

<br/>

## Home Assistant in Virtualbox

Install Home Assistant in a virtual machine. For example download the vdi image for Virtual Box from:

https://www.home-assistant.io/installation/linux/

Also follow the instructions how to setup the virtual machine on that page.

Run the virtual machine.

Open the browser and go to http://homeassistant.local:8123/ to open the Home Assistant Frontend and setup Home Assistant.

<br/>

## Download the Klyqa Integration

Go to Profile (left bottom button) -> Enable "Advanced Mode"

[![Open your Home Assistant instance and show your Home Assistant user's profile.](https://my.home-assistant.io/badges/profile.svg)](https://my.home-assistant.io/redirect/profile/)

Go to Configuration/Settings -> Addons ->
Then go to the addon store and install "Terminal & SSH".

It will be listed on the left bar after the restart of the Home Assistant or start it from Configuration -> Addons -> Terminal & SSH -> Open.

[![Open your Home Assistant instance and show the Supervisor add-on store.](https://my.home-assistant.io/badges/supervisor_store.svg)](https://my.home-assistant.io/redirect/supervisor_store/)

In that terminal enter for installing the Klyqa integration setup following line:

```
cd /config && wget -O klyqa-install.bash https://raw.githubusercontent.com/klyqa/home-assistant-integration/main/install.bash && bash klyqa-install.bash
```

Follow the steps in the script and restart Home Assistant -> Configuration -> System -> Restart (right top).

[![Open your Home Assistant instance and show your settings menu.](https://my.home-assistant.io/badges/config.svg)](https://my.home-assistant.io/redirect/config/)

<br/>

## User Interface Configuration


Go to Settings -> Devices & Services -> Integrations and add the Klyqa integration.

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=Klyqa)

Fill in your Klyqa login details and set it up.

<br/>

## Or Configuration file

Go to the addon store and search for "code" and install VS Code Server.

[![Open your Home Assistant instance and show the Supervisor add-on store.](https://my.home-assistant.io/badges/supervisor_store.svg)](https://my.home-assistant.io/redirect/supervisor_store/)

Afterwards open "Studio Code Server" from the left bar and there go to the configuration.yaml file.

Uncomment and set your Klyqa Login data there and the settings, save the file and restart Home Assistant (Settings -> System -> Restart).

[![Open your Home Assistant instance and show your settings menu.](https://my.home-assistant.io/badges/config.svg)](https://my.home-assistant.io/redirect/config/)

<br/>

## Finishing

After loading the Klyqa Integration, your lights should show up in the Overview Page and in the entities section under settings. If not something went wrong.

[![Open your Home Assistant instance and show your dashboard configs.](https://my.home-assistant.io/badges/lovelace_dashboards.svg)](https://my.home-assistant.io/redirect/lovelace_dashboards/) [![Open your Home Assistant instance and show your entities.](https://my.home-assistant.io/badges/entities.svg)](https://my.home-assistant.io/redirect/entities/)