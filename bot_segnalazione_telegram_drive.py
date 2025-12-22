# bot_segnalazione_telegram.py
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, ConversationHandler
import geopandas as gpd
from shapely.geometry import Point
from datetime import datetime
import os
import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import gspread
from google.oauth2.service_account import Credentials
from flask import Flask
from threading import Thread

# ---------------- CONFIG ---------------- #

SERVICE_ACCOUNT_FILE = "service_account.json" 
DRIVE_FOLDER_ID = "1tAoGCHQJZI2gp5_vb2F3Vh5N8EQMyL0F"
SHEET_ID = "1vSzHUrxrMPeR0PpZyQfrgFYVhDeP_ti7-lzboFcGK2Q"

SCOPES_DRIVE = ['https://www.googleapis.com/auth/drive.file']
SCOPES_SHEET = ['https://www.googleapis.com/auth/spreadsheets']

# Autenticazione Drive
credentials_drive = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES_DRIVE)
drive_service = build('drive', 'v3', credentials=credentials_drive)

# Autenticazione Sheet
credentials_sheet = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES_SHEET)
gc = gspread.authorize(credentials_sheet)
sheet = gc.open_by_key(SHEET_ID).sheet1

# Stati conversazione
CATEGORY, PHOTO, LOCATION, DESCRIPTION = range(4)
user_data_temp = {}
SHAPE_FILE_LOCAL = "segnalazioni.shp"

# ---------------- FLASK UPTIME ---------------- #
app = Flask('')
@app.route('/')
def home(): return "Bot attivo"
Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()

# ---------------- FUNZIONI ---------------- #
def upload_to_drive(file_path, folder_id=DRIVE_FOLDER_ID):
    if not os.path.exists(file_path):
        print(f"File {file_path} non trovato!")
        return None
    file_metadata = {'name': os.path.basename(file_path), 'parents':[folder_id]}
    media = MediaFileUpload(file_path, resumable=True)
    uploaded_file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    print(f"File caricato su Drive con ID: {uploaded_file['id']}")
    return uploaded_file['id']

def add_to_sheet(user_data):
    row = [
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        user_data.get('tipo',''),
        user_data.get('description',''),
        user_data.get('lat',''),
        user_data.get('lon','')
    ]
    sheet.append_row(row)

# ---------------- BOT ---------------- #
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [KeyboardButton("📢 Invia Segnalazione")],
        [KeyboardButton("📖 Istruzioni & Info"), KeyboardButton("⚖️ Privacy")]
    ]
    await update.message.reply_text(
        "Benvenuto! Seleziona un'opzione:",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    )

async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📢 Invia Segnalazione":
        keyboard = [
            [KeyboardButton("🥾 Sentieri e Segnaletica")],
            [KeyboardButton("🗑️ Rifiuti e Decoro")],
            [KeyboardButton("🐾 Fauna e Flora")],
            [KeyboardButton("⚒️ Strutture e Bivacchi")],
            [KeyboardButton("❓ Altro")]
        ]
        await update.message.reply_text(
            "Seleziona la categoria della segnalazione:",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
        )
        return CATEGORY
    elif text == "📖 Istruzioni & Info":
        await update.message.reply_text(
            "Invia segnalazioni tramite foto e posizione GPS. Puoi aggiungere una breve descrizione.\n"
            "ATTENZIONE: Non è un servizio di emergenza. Per soccorso alpino chiama 112."
        )
        return ConversationHandler.END
    elif text == "⚖️ Privacy":
        await update.message.reply_text(
            "Il Parco informa che i dati raccolti (foto, GPS, testi, ID Telegram) "
            "sono utilizzati solo per la gestione delle segnalazioni. Conservazione limitata e anonimizzazione.\n"
            "Per cancellare la segnalazione scrivere a info@pnab.it."
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text("Seleziona un pulsante dal menu principale.")
        return ConversationHandler.END

async def category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_data_temp[user_id] = {'tipo': update.message.text}
    keyboard = [[KeyboardButton("Invia foto")]]
    await update.message.reply_text(
        f"Hai selezionato: {update.message.text}\nOra invia una foto della segnalazione.",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    )
    return PHOTO

async def photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not update.message.photo:
        await update.message.reply_text("Devi inviare una foto!")
        return PHOTO
    local_photo = f"temp_{user_id}.jpg"
    photo_file = await update.message.photo[-1].get_file()
    await photo_file.download_to_drive(local_photo)
    user_data_temp[user_id]['photo_path'] = local_photo
    upload_to_drive(local_photo)
    os.remove(local_photo)

    keyboard = [[KeyboardButton("Invia posizione")]]
    await update.message.reply_text(
        "Foto ricevuta! Ora invia la posizione.",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    )
    return LOCATION

async def location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not update.message.location:
        await update.message.reply_text("Devi inviare la posizione!")
        return LOCATION
    user_data_temp[user_id]['lat'] = update.message.location.latitude
    user_data_temp[user_id]['lon'] = update.message.location.longitude
    await update.message.reply_text("Perfetto! Ora puoi aggiungere una breve descrizione (opzionale).")
    return DESCRIPTION

async def description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_data_temp[user_id]['description'] = update.message.text

    # Salvataggio shapefile
    if os.path.exists(SHAPE_FILE_LOCAL):
        gdf = gpd.read_file(SHAPE_FILE_LOCAL)
    else:
        gdf = gpd.GeoDataFrame(columns=['foto','tipo','didascalia','data'], geometry=[], crs="EPSG:4326")

    new_row = {
        'foto': user_data_temp[user_id].get('photo_path',''),
        'tipo': user_data_temp[user_id]['tipo'],
        'didascalia': user_data_temp[user_id].get('description',''),
        'data': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'geometry': Point(user_data_temp[user_id]['lon'], user_data_temp[user_id]['lat'])
    }

    new_gdf = gpd.GeoDataFrame([new_row], crs="EPSG:4326")
    gdf = pd.concat([gdf,new_gdf], ignore_index=True)
    gdf.to_file(SHAPE_FILE_LOCAL)

    # Carica shapefile su Drive
    for ext in ['shp','shx','dbf','prj','cpg']:
        path = f"segnalazioni.{ext}"
        if os.path.exists(path):
            upload_to_drive(path)

    # Aggiorna Google Sheet
    add_to_sheet(user_data_temp[user_id])

    keyboard = [[KeyboardButton("📢 Invia Segnalazione")]]
    await update.message.reply_text(
        "Grazie! La tua segnalazione è stata registrata.\nVuoi inviarne un'altra?",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    )
    del user_data_temp[user_id]
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id in user_data_temp:
        del user_data_temp[user_id]
    await update.message.reply_text("Segnalazione annullata.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# ---------------- SETUP BOT ---------------- #
TOKEN = os.environ['TELEGRAM_TOKEN']
app_bot = ApplicationBuilder().token(TOKEN).build()

conv_handler = ConversationHandler(
    entry_points=[CommandHandler('start', start), MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_handler)],
    states={
        CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, category)],
        PHOTO: [MessageHandler(filters.PHOTO, photo)],
        LOCATION: [MessageHandler(filters.LOCATION, location)],
        DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, description)],
    },
    fallbacks=[CommandHandler('cancel', cancel)],
)

app_bot.add_handler(conv_handler)
app_bot.run_polling()
