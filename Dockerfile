FROM ghcr.io/home-assistant/home-assistant:stable

# Needed dependencies for building the Klyqa integration python requirements.
RUN apk --no-cache add musl-dev linux-headers g++

RUN mkdir -p /config/custom_components/
RUN git clone https://github.com/klyqa/home-assistant-integration /config/custom_components/klyqa
RUN python -m pip install -r /config/custom_components/klyqa/requirements.txt

