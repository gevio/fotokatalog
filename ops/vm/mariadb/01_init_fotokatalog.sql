CREATE DATABASE IF NOT EXISTS fotokatalog
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'fotokatalog'@'localhost'
  IDENTIFIED BY 'CHANGE_ME_STRONG_PASSWORD';

GRANT ALL PRIVILEGES ON fotokatalog.* TO 'fotokatalog'@'localhost';
FLUSH PRIVILEGES;
