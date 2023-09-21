# Supervisor

This service is responsible for serving end-user requests and exchanges
data between all other services.

## Configuration

As this service needs to send requests to other services, there's a `network.cfg`
file with all network information for other services.

You don't need to change this file until you want to run some services outside
container network — if so, you need to change host and port to one's that
you use.

There's also a configuration of linking methods hyperparameters for 
Linker service in `linker_config.json` file depending on embedding source.


## Building container

To build just use `sh build.sh` on the project root.

## Running

This application is built using FastAPI, so you may use
```
uvicorn --app-dir=src main:app
```
command.

NOTE: running this outside of container requires changing corresponding host
and port in Supervisor service configuration.

But since this service is a part of inbrief project, you may use `docker-compose up/docker-compose start scraper`
in any child directory. 

## API

Port: 8000 -> 8000

### POST /api/summarize
- `config (dict)` — request configuration
    - `embedding_source (enum)` — one of the following: `"ft+mlm"`, `"openai"`
    - `linking_method (enum)` — responsible for linking posts, one of the following: `"dbscan"`, `"bm25"`
    - `summary_method (enum)` — responsible for summarazing method, one of the following: `"openai"`, `"bart"`
    - `density (enum)` — controls density of summary, one of following: `small`, `average`, `large`
    - `editor (str)` — controls style of output summary
- `payload (dict)` — contains all other required information for serving request
    - `channels (list)` — list of channels that need to be parsed by Scraper service
    - `end_date (datetime)` — the oldest message date to be retrieved
    - `offset_date (datetime)` — the newest message date to be retrieved from

Example request:
```
{
  "config": {
    "embedding_source": "ft+mlm",
    "linking_method": "dbscan",
    "summary_method": "openai",
    "density": "small",
    "editor": "<any describing string>"
  },
  "payload": {
    "channels": [
      "string"
    ],
    "end_date": "01/01/01 00:00:00",
    "offset_date": "08/19/23 12:34:56"
  }
}
```
