from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, ConversationHandler
import geopandas as gpd
from shapely.geometry import Point
from datetime import datetime
import os
import pandas as pd

# ---------------- CONFIGURAZIONE CARTELLA DRIVE ---------------- #
SHAPE_FOLDER = r"M:\Documenti\Ambientale\LorenzoStefani\SEGNALAZIONI_PNAB"
os.makedirs(SHAPE_FOLDER, exist_ok=True)
SHP_FILE = os.path.join(SHAPE_FOLDER, "segnalazioni.shp")

# Stati della conversazione
FOTO, POSIZIONE, TIPO, DIDASCALIA = range(4)

# Dati temporanei degli utenti
user_data_temp = {}

# Inizializza shapefile se non esiste
if not os.path.exists(SHP_FILE):
    gdf = gpd.GeoDataFrame(columns=['foto', 'tipo', 'didascalia', 'data'], geometry=[], crs="EPSG:4326")
    gdf.to_file(SHP_FILE)

# ----------------- FUNZIONI DEL BOT ----------------- #

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
    user_data_temp[user_id]['foto'] = update.message.photo[-1].file_id

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

    # Leggi shapefile esistente
    gdf = gpd.read_file(SHP_FILE)

    # Crea nuovo punto
    new_row = {
        'foto': user_data_temp[user_id]['foto'],
        'tipo': user_data_temp[user_id]['tipo'],
        'didascalia': user_data_temp[user_id]['didascalia'],
        'data': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'geometry': Point(user_data_temp[user_id]['lon'], user_data_temp[user_id]['lat'])
    }

    # Aggiungi nuova segnalazione usando pd.concat (compatibile pandas 2.x)
    new_gdf = gpd.GeoDataFrame([new_row], crs="EPSG:4326")
    gdf = pd.concat([gdf, new_gdf], ignore_index=True)
    gdf.to_file(SHP_FILE)  # salva direttamente nella cartella Drive

    await update.message.reply_text(
        "Segnalazione completata! Grazie per il tuo contributo.",
        reply_markup=ReplyKeyboardRemove()
    )

    # Pulisci dati temporanei
    del user_data_temp[user_id]
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id in user_data_temp:
        del user_data_temp[user_id]
    await update.message.reply_text("Segnalazione annullata.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# ----------------- COSTRUZIONE DEL BOT ----------------- #

app = ApplicationBuilder().token("8376287781:AAG9CV_cAmvhsGiNvN83af50W2-kyJ0AUtU").build()

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

app.add_handler(CommandHandler("start", start))
app.add_handler(conv_handler)

app.run_polling()
