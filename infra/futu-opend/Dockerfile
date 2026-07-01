FROM ubuntu:24.04 AS downloader

ARG FUTU_OPEND_URL=https://www.futunn.com/download/fetch-lasted-link?name=opend-ubuntu
RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl tar \
  && rm -rf /var/lib/apt/lists/*
WORKDIR /tmp/futu
RUN curl -L --fail "$FUTU_OPEND_URL" -o opend.tar.gz \
  && tar -xzf opend.tar.gz \
  && mkdir -p /opt/futu-opend \
  && find . -path '*/Futu_OpenD_*_Ubuntu18.04/FutuOpenD' -printf '%h\n' -quit \
    | xargs -I{} cp -a {}/. /opt/futu-opend/

FROM ubuntu:24.04

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates openssl telnet \
  && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/futu-opend
COPY --from=downloader /opt/futu-opend/ /opt/futu-opend/
COPY start.sh /usr/local/bin/futu-opend-start
RUN chmod +x /opt/futu-opend/FutuOpenD /usr/local/bin/futu-opend-start \
  && mkdir -p /var/log/futu-opend

ENV FUTU_OPEND_API_PORT=11111
ENV FUTU_OPEND_WEBSOCKET_PORT=33333
ENV FUTU_OPEND_TELNET_PORT=22222
ENV FUTU_OPEND_LANG=chs
ENV FUTU_OPEND_LOG_LEVEL=info

CMD ["futu-opend-start"]
