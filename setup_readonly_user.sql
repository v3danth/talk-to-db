-- Read-only account used by the talk-to-db agent. SELECT + SHOW VIEW only: it cannot write, drop, or alter.
CREATE USER IF NOT EXISTS 'talk_to_db_ro'@'localhost' IDENTIFIED BY 'talk_to_db_ro_local';
CREATE USER IF NOT EXISTS 'talk_to_db_ro'@'127.0.0.1' IDENTIFIED BY 'talk_to_db_ro_local';
GRANT SELECT, SHOW VIEW ON `mis_40_50`.* TO 'talk_to_db_ro'@'localhost';
GRANT SELECT, SHOW VIEW ON `mis_40_50`.* TO 'talk_to_db_ro'@'127.0.0.1';
FLUSH PRIVILEGES;
