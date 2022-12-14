FROM ghcr.io/home-assistant/home-assistant:stable

# Needed dependencies for building the Klyqa integration python requirements.
# RUN apk --no-cache --update add musl-dev linux-headers g++ python3-dev gfortran py-pip build-base
RUN apk --no-cache --update add build-base

COPY install_to_ha.sh /install_to_ha.sh
RUN bash -xc /install_to_ha.sh /config
# RUN mkdir -p /config/custom_components
# RUN git clone -b development https://github.com/klyqa/home-assistant-integration /config/custom_components/klyqa
# RUN python -m pip install -r /config/custom_components/klyqa/requirements.txt

