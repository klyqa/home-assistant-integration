# Klyqa Home Assistant Custom Integration

## Lamp Support
- Scene effects
- Lamp temperature color
- Lamp RGB color
- Lamp brightness
- Lamp transition time
- Lamp Rooms
- Klyqa App Cloud synchronisation

## Install Home Assistant (HA)
Local ways to install home assistant:<br />
1. Docker:<br />
https://www.home-assistant.io/installation/linux#install-home-assistant-container<br />
Make a config folder on your filesystem and tell the docker about the path.<br />
<br />
or<br /><br />
2. Dev container (Visual Studio Code, docker with full debug support):<br />
```
git clone https://github.com/home-assistant/core.git
```
Your config folder will then be in your cloned folder under config. It will be mapped into the devcontainer. So you can put and change there what you need.<br /><br />
Open that path in VS Code and hit reopen as a dev container.<br />
Add to .devcontainer/devcontainer.json runArgs network host mode so you can open and close network sockets:<br />
```
"runArgs": [ ... , "--network=host" ]
```
Start HA with "start debug" or "run" in VS Code.

or<br /><br />
3. You have a Hass OS running and have access to it.<br />

## Developer Documentation

https://developers.home-assistant.io/docs/development_environment

## Integration
Put the integration folder into your home assistant config custom_components folder.<br />
<br />
E. g. config/custom_components/klyqa<br />
```
cd config/custom_components && git clone https://github.com/fsqcx/klyqa_ha_custom_component klyqa
```

You can control the logger in the configuration.yaml in your config folder. For example set info level for home assistant and debug level for the klyqa integration:<br />
```
# Configure a default setup of Home Assistant (frontend, api, etc)
default_config:
logger:
  default: info
  logs:
    # individual log level for the klyqa integration
    custom_components.klyqa: debug
```

## Start
Locally you found Home Assistant normally under 127.0.0.1:8123 in you browser.<br />
Set up home assistant account and configuration.<br />
Then you can set up Klyqa Integration either via config flow in the webinterface: Configuration > Devices & Services > + Add Integration > Klyqa<br /><br />
or<br /><br />
in the config/configuration.yaml:<br />
```
light:
  - platform: klyqa
    username: your-email@domain.com
    password: your_password
    polling: True
    scan_interval: 30
    sync_rooms: True
    host: http://localhost:3000 # when working with devstack, current option, reaching app-api
```
You can store your password into your config/secrets.yaml and put for example in the password value "!secret klyqa_password_identifier"<br />
using config/secrets.yaml:
```
klyqa_password_identifier: your_password
```
## Klyqa Lamps in HA
When the integration is running it should synchronize the klyqa account configuration and search the lamps in the network. They should appear under Configuration > Devices & Services > Devices & Entities.<br /><br />
Afterwards you add entity cards to the Overview Dashboard a. k. a. "Lovelace".<br />
Click Overview > Click Three dots Menu (Right top corner) > Edit Dashboard > Click + ADD CARD > Light Card Configuration > Select Klyqa Lamp Entity and save