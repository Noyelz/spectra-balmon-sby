# agar tidak perlu mengetik command panjang pajang makanya menggunakan makefile
.PHONY: dev up down logs ps clean

# menjalankan Docke Compose untuk development (otomatis baca override file)
dev:
	docker compose up -d

# Sama dengan dev (alias)
up: dev

# Mematikan container (Volume TIDAK dihapus)
down:
	docker compose down

# Mematikan container DAN juga menghapus (BAHAYA: JANGAN PAKAI KALAU TIDAK TAU(JANGAN PAKAI DI PROD))
clean:
	docker compose down -v

# Melihat status container
ps:
	docker compose ps

# Melihat log semua container secara live
logs:
	docker compose logs -f

# Masuk ke shell PostgreSQL
psql:
	docker compose exec postgres-db psql -U $${POSTGRES_USER} -d $${POSTGRES_DB}

# Masuk ke shell Redis
redis-cli:
	docker compose exec redis redis-cli