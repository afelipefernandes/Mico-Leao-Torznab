# Mico Leão Dublado Torznab

Características

🔄 proxy para consumo da api do Mico Leão Dublado

🎯 Integração com Prowlarr/Radarr



## Getting Started


### Quick Installation (Docker Compose)


```yaml
version: "3.8"Add commentMore actions

services:
  Mico-Leao-Torznab:
    container_name: Mico-Leao-Torznab
    build:
      context: .
    ports:
      - "5050:5050"
    restart: unless-stopped
```
