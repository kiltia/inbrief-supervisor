# Supervisor (Outdated. API may be changed)

This service is responsible for serving end-user requests and exchanges
data between all other services.

![arch](../docs/arch.png "Top-level-architecture")

## Configuration

As this service needs to send requests to other services, there's a `network.cfg`
file with all network information for other services.

You don't need to change this file until you want to run some services outside
container network — if so, you need to change host and port to one's that
you use.

There's also a configuration of linking methods hyperparameters for
Linker service in `linker_config.json` file depending on embedding source.

## Building container

To build just use `sh build.sh` in the project root.

## Running

This application is built using FastAPI, so you may use

```
uvicorn --app-dir=src main:app [--reload]
```

command in service root directory.

NOTE: running this outside of container requires changing corresponding host
and port in Supervisor service configuration.

Since this service is a part of InBrief project, you may use `docker compose up scraper`
in any child directory.

## API

Port: 8000 -> 8000

### POST /api/fetch

This endpoint designed to get posts from Telegram API and link them into
groups called stories.

#### Example request

Request body:

- `chat_id (int)` — unique Telegram chat ID
- `end_date (date)` — the latest message date
- `offset_date (date)` — the most recent message date

```
{
  "chat_id": 0,
  "end_date": "21/10/23 00:00:00",
  "offset_date": "26/10/23 00:00:00"
}
```

#### Example response

OK 200

Request body:

- `config_id (int)` — ID of user config for summarization
- `story_ids (List[UUID])` — list of story IDs to be passed to `/api/summarize`
  endpoint

```
{
  "config_id": 0,
  "story_ids": [
    "fe9ecfac-572c-4781-b5d5-b8247f40c975",
    "be25d950-cb68-4d3c-9d55-cf550d1fc819",
    "6b56a071-17a3-465c-9d84-8e0bcb562483"
  ]
}
```

### POST /api/summarize

This endpoint designed to get summary for one story given list of required
densities.

#### Example request

Request body:

- `chat_id (int)` — unique Telegram chat ID
- `config_id (int)` — ID of config given in response of API fetch method
- `story_id (UUID)` — unique story ID given in response of API fetch method
- `required_density (List[Enum])` — list of required density

```
{
  "chat_id": 0,
  "config_id": 0,
  "story_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "required_density": [
    "small", "large"
  ]
}
```

#### Example response

OK 200

Response body:

```
{
  "large": {
    "title": "some_text",
    "summary": "some_text",
    "references": [
      "t.me/hidethelight/126"
    ]
  },
  "small": {
    "title": "some_text",
    "summary": "some_text",
    "references": [
      "t.me/hidethelight/126"
    ]
  }
}
```

### POST /api/user

This endpoint designed to register a new user.

#### Example request

Request body:

- `chat_id (int)` — unique Telegram chat ID

```
{
  "chat_id": 0
}
```

#### Example response

OK 204

### GET /api/user/{chat_id}/presets

This endpoint help front-end with retrieving all presets for a giving user.

#### Example request

Path parameters:

- `chat_id (int)` — unique Telegram chat ID

#### Example response

OK 200

Response body:

- `chat_id (int)` — unique Telegram chat ID.
- `chat_folder_link (str)` — link to chat folder with user channels
- `editor_prompt` — additional prompt to be passed to editor service
- `preset_name` — name of a preset given by user

```
[
  {
    "preset_id": "e5e4c1dc-f5d0-4f62-842f-5b7653d8ae75",
    "chat_folder_link": "https://t.me/addlist/6JnbsxFqcFNjMDgy",
    "editor_prompt": "some_prompt",
    "preset_name": "some_name"
  }
]
```

### PATCH /api/user/{chat_id}/presets

This endpoint is designed to change current preset for a giving user

#### Example request

Path parameters:

- `chat_id (int)` — unique Telegram chat ID

Request body:

- `cur_preset (UUID)` — unique id of preset

```
{
  "cur_preset": "98fc845c-02a1-4084-b365-3fa5386fecba"
}
```

### Example response

OK 204

### PATCH /api/preset

This endpoint can be used to edit any parameters of existing preset —
change its name, editor prompt message and even make in inactive.

#### Example request

Query parameters:

- `chat_id (int)` — unique Telegram chat ID

Request body:

- `preset_id (uuid | None)` — unique preset ID
- `preset_name (str | None)` — name of preset
- `chat_folder_link (str | None)` — chat folder link
- `editor_prompt (str | None)` — additional prompt to be passed to editor service
- `inactive (str | None)` — inactivity of preset

```
{
  "chat_id": 0,
  "preset_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "preset_name": "some_name",
  "chat_folder_link": "https://t.me/addlist/6JnbsxFqcFNjMDgy",
  "editor_prompt": "some_prompt",
  "inactive": true
}
```

#### Example response

OK 204

### POST /api/preset

This endpoints allows creating new presets for certain user.

#### Example request

Query parameters:

- `chat_id`

Request body:

```
{
  "preset_name": "some_preset",
  "chat_folder_link": "https://t.me/addlist/6JnbsxFqcFNjMDgy",
  "editor_prompt": "some_prompt"
}
```

#### Example response

Request body:

```
{
  "preset_id": "c1acc910-5fa2-49fa-9905-80be0af614eb"
}
```

### POST /api/callback

#### Example request

Request body:

```
{
  "callback_data": some_valid_json
}
```

#### Example response

OK 204

### PATCH /api/callback

Request body:

```
{
  "callback_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "callback_data": some_valid_json
}
```

#### Example response

OK 204

### GET /api/callback/{callback_id}

#### Example request

Path parameters:

- `callback_id` — unique callback ID

#### Example response

OK 200 with any valid JSON
