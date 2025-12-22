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
from flask import Flask
from threading import Thread

# ---------------- CONFIG ---------------- #

# Google Drive
SERVICE_ACCOUNT_FILE = "service_account.json"  
DRIVE_FOLDER_ID = "1tAoGCHQJZI2gp5_vb2F3Vh5N8EQMyL0F"

SCOPES = ['https://www.googleapis.com/auth/drive.file']
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)
drive_service = build('drive', 'v3', credentials=credentials)

# Stati della conversazione
FOTO, POSIZIONE, TIPO, DIDASCALIA = range(4)
user_data_temp = {}

# Shapefile temporaneo locale
SHAPE_FILE_LOCAL = "segnalazioni.shp"

# Flask per ping UptimeRobot
app = Flask('')

@app.route('/')
def home():
    return "Bot attivo"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

Thread(target=run_flask).start()

# ---------------- FUNZIONI DRIVE ---------------- #

def upload_to_drive(file_path, folder_id=DRIVE_FOLDER_ID):
    """Carica file su Google Drive"""
    file_metadata = {
        'name': os.path.basename(file_path),
        'parents': [folder_id]
    }
    media = MediaFileUpload(file_path, resumable=True)
    file = drive_service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id'
    ).execute()
    print(f"File caricato su Drive con ID: {file['id']}")
    return file['id']

# ---------------- FUNZIONI BOT ---------------- #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Benvenuto! Usa /segnala per inviare una segnalazione.")

async def segnala(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_data_temp[user_id] = {}
    await update.message.reply_text("Perfetto! Inviami una foto della segnalazione.")
    return FOTO

async def foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not update.message.photo:
        await update.message.reply_text("Devi inviare una foto!")
        return FOTO

    # Scarica foto temporaneamente su Replit
    local_photo = f"temp_{user_id}.jpg"
    photo_file = await update.message.photo[-1].get_file()
    await photo_file.download_to_drive(local_photo)
    user_data_temp[user_id]['foto'] = local_photo

    # Carica foto su Drive e cancella locale
    upload_to_drive(local_photo)
    os.remove(local_photo)

    keyboard = [[KeyboardButton("Invia posizione", request_location=True)]]
    await update.message.reply_text(
        "Grazie! Ora inviami la posizione.",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    )
    return POSIZIONE

async def posizione(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not update.message.location:
        await update.message.reply_text("Devi inviare la posizione!")
        return POSIZIONE
    user_data_temp[user_id]['lat'] = update.message.location.latitude
    user_data_temp[user_id]['lon'] = update.message.location.longitude

    keyboard = [['Ambiente', 'Sentieri', 'Ponti danneggiati']]
    await update.message.reply_text(
        "Seleziona il tipo di segnalazione:",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    )
    return TIPO

async def tipo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    scelta = update.message.text
    if scelta not in ['Ambiente', 'Sentieri', 'Ponti danneggiati']:
        await update.message.reply_text("Scegli tra Ambiente, Sentieri o Ponti danneggiati.")
        return TIPO
    user_data_temp[user_id]['tipo'] = scelta
    await update.message.reply_text(
        "Ora scrivi una breve descrizione della segnalazione.",
        reply_markup=ReplyKeyboardRemove()
    )
    return DIDASCALIA

async def didascalia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_data_temp[user_id]['didascalia'] = update.message.text

    # Leggi shapefile esistente o creane uno nuovo
    if os.path.exists(SHAPE_FILE_LOCAL):
        gdf = gpd.read_file(SHAPE_FILE_LOCAL)
    else:
        gdf = gpd.GeoDataFrame(columns=['foto','tipo','didascalia','data'], geometry=[], crs="EPSG:4326")

    # Crea nuovo punto
    new_row = {
        'foto': user_data_temp[user_id]['foto'],  # su Drive hai già caricato la foto
        'tipo': user_data_temp[user_id]['tipo'],
        'didascalia': user_data_temp[user_id]['didascalia'],
        'data': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'geometry': Point(user_data_temp[user_id]['lon'], user_data_temp[user_id]['lat'])
    }

    # Aggiungi al GeoDataFrame
    new_gdf = gpd.GeoDataFrame([new_row], crs="EPSG:4326")
    gdf = pd.concat([gdf, new_gdf], ignore_index=True)
    gdf.to_file(SHAPE_FILE_LOCAL)

    # Carica shapefile su Drive (tutti i file .shp/.shx/.dbf/.prj/.cpg)
    for ext in ['shp','shx','dbf','prj','cpg']:
        file_path = f"segnalazioni.{ext}"
        if os.path.exists(file_path):
            upload_to_drive(file_path)

    await update.message.reply_text(
        "Segnalazione completata! Grazie per il tuo contributo.",
        reply_markup=ReplyKeyboardRemove()
    )
    del user_data_temp[user_id]
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id in user_data_temp:
        del user_data_temp[user_id]
    await update.message.reply_text("Segnalazione annullata.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# ----------------- BOT ----------------- #

TOKEN = os.environ['TELEGRAM_TOKEN']

app_bot = ApplicationBuilder().token(TOKEN).build()

conv_handler = ConversationHandler(
    entry_points=[CommandHandler('segnala', segnala)],
    states={
        FOTO: [MessageHandler(filters.PHOTO, foto)],
        POSIZIONE: [MessageHandler(filters.LOCATION, posizione)],
        TIPO: [MessageHandler(filters.TEXT & ~filters.COMMAND, tipo)],
        DIDASCALIA: [MessageHandler(filters.TEXT & ~filters.COMMAND, didascalia)],
    },
    fallbacks=[CommandHandler('cancel', cancel)],
)

app_bot.add_handler(CommandHandler("start", start))
app_bot.add_handler(conv_handler)

app_bot.run_polling()
