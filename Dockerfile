FROM ghcr.io/home-assistant/home-assistant:stable

RUN mkdir -p /config/custom_components/
RUN git clone https://github.com/klyqa/home-assistant-integration /config/custom_components/klyqa
RUN python -m pip install -r /config/custom_components/klyqa/requirements.txt

