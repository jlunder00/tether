# Upgrading

## Pulling updates

```bash
cd ~/tether
git pull
```

## Applying database migrations

Tether uses Alembic for database migrations. After pulling, check whether a migration is needed:

```bash
docker compose run --rm api alembic upgrade head
```

This is safe to run even if there are no new migrations — it's a no-op if already up to date.

## Restarting services

```bash
docker compose up -d
```

Or, if you built a new image:

```bash
docker compose pull
docker compose up -d
```

## Checking what changed

Look at the release notes or the commit log to see whether any manual steps are required:

```bash
git log --oneline HEAD~10..HEAD
```

<!-- TODO: Add notes about the CI/CD path (IMAGE_TAG written by deploy.yml) and the make restart workflow once config-loader-redesign lands. -->
