# ehforwarderbot

## install

```console
$ git clone https://github.com/jiz4oh/ehforwarderbot ehforwarderbot
```

## configuration

1. in `profiles/default/blueset.telegram/config.yaml`
   1. Update `token`
   2. Update userid in `admins`
2. (optional) in `profiles/default/config.yaml`
   1. add extra slave_channels

## start

```console
$ cd ehforwarderbot
# comwechat
$ docker compose up -d
# web
$ docker compose -f ./docker-compose.web.yaml up -d
```

