Easiest way to install Home Assistant with the Klyqa Integration

Install Home Assistant in a virtual machine. For example download the vdi image for Virtual Box from:

https://www.home-assistant.io/installation/linux/

Also follow the instructions how to setup the virtual machine on that page.

Then go to the addon store and install Terminal & SSH and search for "code" and install vs code.

It will probably be listed on the left bar after the restart of the Home Assistant.

In that terminal enter for installing the Klyqa integration setup:

cd /config && wget -O klyqa-install.bash https://raw.githubusercontent.com/klyqa/home-assistant-integration/main/install.bash && bash klyqa-install.bash

Follow the steps and afterwards open "Studio Code Server" from the left bar and there the configuration.yaml file.

Uncomment and set your Klyqa Login data there and settings, save the file and restart Home Assistant.

After loading your lights from your Klyqa Account should show up in the Overview and the entities section in settings.
