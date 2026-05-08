# TrackHub Backend MVP

Минимальный backend для Android-приложения музыкального сервиса.

## Что уже реализовано

- Регистрация пользователя
- Авторизация пользователя через JWT
- Получение текущего пользователя
- Загрузка mp3/wav/m4a треков
- Хранение аудиофайлов в папке `uploads/tracks`
- Хранение метаданных в PostgreSQL
- Общий список треков
- Список моих треков
- Поиск треков по названию и автору
- Stream endpoint для воспроизведения трека в Android через Media3 / ExoPlayer
- Лайки и отмена лайка
- Комментарии
- Плейлисты
- Добавление/удаление треков из плейлиста

## Запуск

### 1. Запустить PostgreSQL

```bash
docker compose up -d
```

### 2. Создать виртуальное окружение

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Linux/macOS:

```bash
source .venv/bin/activate
```

### 3. Установить зависимости

```bash
pip install -r requirements.txt
```

### 4. Создать `.env`

```bash
cp .env.example .env
```

На Windows можно просто скопировать файл `.env.example` и переименовать копию в `.env`.

### 5. Запустить backend

```bash
uvicorn app.main:app --reload
```

API будет доступен по адресу:

```text
http://127.0.0.1:8000
```

Swagger UI:

```text
http://127.0.0.1:8000/docs
```

## Основные endpoints

### Health check

```http
GET /api/health
```

### Регистрация

```http
POST /api/auth/register
Content-Type: application/json

{
  "username": "selim",
  "email": "selim@example.com",
  "password": "123456"
}
```

### Вход

```http
POST /api/auth/login
Content-Type: application/json

{
  "email": "selim@example.com",
  "password": "123456"
}
```

В ответе будет `access_token`. Его нужно передавать в защищённые запросы:

```http
Authorization: Bearer YOUR_TOKEN
```

### Загрузка трека

```http
POST /api/tracks/upload
Authorization: Bearer YOUR_TOKEN
Content-Type: multipart/form-data

fields:
- title: Track title
- author: Track author
- file: audio file
```

### Список треков

```http
GET /api/tracks
```

### Поиск треков

```http
GET /api/tracks/search?query=night
```

### Воспроизведение трека

```http
GET /api/tracks/{track_id}/stream
```

Именно этот URL Android-приложение передаёт в Media3 / ExoPlayer.

### Лайк

```http
POST /api/tracks/{track_id}/like
Authorization: Bearer YOUR_TOKEN
```

### Комментарии

```http
POST /api/tracks/{track_id}/comments
Authorization: Bearer YOUR_TOKEN
Content-Type: application/json

{
  "text": "Классный трек"
}
```

```http
GET /api/tracks/{track_id}/comments
```

### Плейлисты

```http
POST /api/playlists
Authorization: Bearer YOUR_TOKEN
Content-Type: application/json

{
  "name": "Любимые треки"
}
```

```http
POST /api/playlists/{playlist_id}/tracks/{track_id}
Authorization: Bearer YOUR_TOKEN
```

## Как Android будет воспроизводить трек

Backend возвращает объект трека с полем:

```json
{
  "id": 1,
  "title": "Night Drive",
  "author": "User123",
  "stream_url": "/api/tracks/1/stream"
}
```

В Android нужно собрать полный URL:

```text
http://10.0.2.2:8000/api/tracks/1/stream
```

Для Android Emulator `10.0.2.2` означает localhost компьютера.

Пример для Media3 / ExoPlayer:

```kotlin
val mediaItem = MediaItem.fromUri("http://10.0.2.2:8000/api/tracks/1/stream")
player.setMediaItem(mediaItem)
player.prepare()
player.play()
```

## Важные замечания для MVP

- Таблицы создаются автоматически при старте приложения через `Base.metadata.create_all`.
- Для учебного проекта это нормально.
- Для production-версии лучше использовать Alembic migrations.
- Аудиофайлы не хранятся в PostgreSQL. В базе хранится только имя файла и метаданные.
- Внешний музыкальный API не используется в основной реализации.
