import Database from 'better-sqlite3'
import path from 'path'
import fs from 'fs'
import dotenv from 'dotenv'

dotenv.config({ path: path.resolve(__dirname, '../../../../.env') })

// DB lives at HiScribe/data/hiscribe.db — shared with Python pipeline
const DB_PATH = process.env.DB_PATH
  ? path.resolve(__dirname, '../../../../', process.env.DB_PATH)
  : path.resolve(__dirname, '../../../../data/hiscribe.db')

const SCHEMA_PATH = path.resolve(__dirname, '../../../../schema.sql')

fs.mkdirSync(path.dirname(DB_PATH), { recursive: true })

export const db = new Database(DB_PATH)
db.pragma('journal_mode = WAL')
db.pragma('foreign_keys = ON')

// Initialize schema on first boot
if (fs.existsSync(SCHEMA_PATH)) {
  const schema = fs.readFileSync(SCHEMA_PATH, 'utf-8')
  db.exec(schema)
  console.log('[db] Schema initialized at', DB_PATH)
} else {
  console.warn('[db] schema.sql not found at', SCHEMA_PATH)
}
