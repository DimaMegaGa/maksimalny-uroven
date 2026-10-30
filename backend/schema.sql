-- Ориентир для схемы. Применять вручную только в отдельной тестовой БД.
-- Точные типы, миграции и подключение подбираются под СУБД друга.
-- Не содержит стартовых пользователей, паролей или заданий.
-- JSON-поля ниже хранятся как TEXT для простоты переноса между СУБД.

CREATE TABLE users (
  id TEXT PRIMARY KEY,
  role TEXT NOT NULL CHECK (role IN ('student', 'teacher')),
  name TEXT NOT NULL,
  school TEXT NOT NULL,
  class_name TEXT NOT NULL DEFAULT '',
  avatar TEXT NOT NULL DEFAULT '',
  achievements_json TEXT NOT NULL DEFAULT '[]',
  created_at BIGINT NOT NULL
);
CREATE TABLE credentials (
  user_id TEXT PRIMARY KEY REFERENCES users(id),
  identity_key TEXT NOT NULL UNIQUE,
  code_hash TEXT NOT NULL,
  salt TEXT NOT NULL
);
CREATE TABLE sessions (
  token_hash TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  expires_at BIGINT NOT NULL
);
CREATE TABLE tasks (
  id TEXT PRIMARY KEY,
  teacher_id TEXT NOT NULL REFERENCES users(id),
  school TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  instructions TEXT NOT NULL DEFAULT '',
  subject TEXT NOT NULL,
  points INTEGER NOT NULL CHECK (points BETWEEN 1 AND 100),
  deadline TEXT NOT NULL,
  target_type TEXT NOT NULL CHECK(target_type IN ('student','class','parallel')),
  target TEXT NOT NULL,
  created_at BIGINT NOT NULL
);
CREATE INDEX tasks_teacher ON tasks(teacher_id);
CREATE INDEX tasks_audience ON tasks(school,target_type,target);
CREATE TABLE submissions (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks(id),
  user_id TEXT NOT NULL REFERENCES users(id),
  review TEXT NOT NULL,
  photos_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected')),
  created_at BIGINT NOT NULL,
  checked_at BIGINT,
  UNIQUE(task_id,user_id)
);
CREATE TABLE exchanges (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  teacher_id TEXT NOT NULL REFERENCES users(id),
  subject TEXT NOT NULL,
  cost INTEGER NOT NULL CHECK(cost > 0),
  status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected')),
  created_at BIGINT NOT NULL
);
CREATE TABLE ledger (
  id TEXT PRIMARY KEY,
  event_id TEXT NOT NULL UNIQUE,
  user_id TEXT NOT NULL REFERENCES users(id),
  amount INTEGER NOT NULL CHECK(amount <> 0),
  text TEXT NOT NULL,
  created_at BIGINT NOT NULL
);
CREATE INDEX ledger_user ON ledger(user_id);
CREATE TABLE notifications (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  event_id TEXT NOT NULL,
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  text TEXT NOT NULL,
  target TEXT NOT NULL,
  is_read INTEGER NOT NULL DEFAULT 0 CHECK(is_read IN (0,1)),
  celebrated INTEGER NOT NULL DEFAULT 0 CHECK(celebrated IN (0,1)),
  extra_json TEXT NOT NULL DEFAULT '{}',
  created_at BIGINT NOT NULL,
  UNIQUE(user_id,event_id)
);
CREATE TABLE workspace_revision (
  id INTEGER PRIMARY KEY CHECK(id=1),
  revision BIGINT NOT NULL
);
INSERT INTO workspace_revision(id,revision) VALUES(1,0);
