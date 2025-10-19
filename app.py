import os
import json
import gdown
import requests
import sqlite3
import re
from flask import Flask, jsonify
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
import threading
import logging
import traceback

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Zorunlu kanallar
REQUIRED_CHANNELS = ["@nabisystem", "@watronschecker"]

# Google Drive File ID
DRIVE_FILE_ID = "1jqHxXLH8-7qj1mCHVtJg-H3XjbQXz5EN"
DRIVE_URL = f"https://drive.google.com/uc?id={DRIVE_FILE_ID}"

# Database için
def init_db():
    try:
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                remaining_searches INTEGER DEFAULT 3,
                invited_users INTEGER DEFAULT 0,
                total_invites INTEGER DEFAULT 0,
                bonus_received BOOLEAN DEFAULT FALSE
            )
        ''')
        conn.commit()
        conn.close()
        logger.info("✅ Kullanıcı database tablosu oluşturuldu")
    except Exception as e:
        logger.error(f"❌ Database hatası: {e}")

def get_user_data(user_id):
    try:
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        
        if not user:
            cursor.execute('''
                INSERT INTO users (user_id, remaining_searches, invited_users, total_invites, bonus_received) 
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, 3, 0, 0, False))
            conn.commit()
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            user = cursor.fetchone()
        
        conn.close()
        
        if user:
            return {
                'user_id': user[0],
                'remaining_searches': user[1],
                'invited_users': user[2],
                'total_invites': user[3],
                'bonus_received': bool(user[4])
            }
        else:
            return {
                'user_id': user_id,
                'remaining_searches': 3,
                'invited_users': 0,
                'total_invites': 0,
                'bonus_received': False
            }
            
    except Exception as e:
        logger.error(f"❌ get_user_data hatası: {e}")
        return {
            'user_id': user_id,
            'remaining_searches': 3,
            'invited_users': 0,
            'total_invites': 0,
            'bonus_received': False
        }

def update_user_searches(user_id, new_count):
    try:
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET remaining_searches = ? WHERE user_id = ?', (new_count, user_id))
        conn.commit()
        conn.close()
        logger.info(f"✅ Kullanıcı {user_id} sorgu hakkı güncellendi: {new_count}")
    except Exception as e:
        logger.error(f"❌ update_user_searches hatası: {e}")

def add_invite(user_id):
    try:
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        
        cursor.execute('SELECT invited_users, bonus_received FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        
        if result:
            current_invites = result[0]
            bonus_received = bool(result[1])
            new_invites = current_invites + 1
            
            logger.info(f"📨 Davet ekleniyor: {user_id} -> {current_invites} -> {new_invites}")
            
            cursor.execute('UPDATE users SET invited_users = ?, total_invites = total_invites + 1 WHERE user_id = ?', 
                          (new_invites, user_id))
            
            if new_invites >= 3 and not bonus_received:
                cursor.execute('SELECT remaining_searches FROM users WHERE user_id = ?', (user_id,))
                current_searches = cursor.fetchone()[0]
                new_searches = current_searches + 30
                
                cursor.execute('UPDATE users SET remaining_searches = ?, bonus_received = TRUE WHERE user_id = ?', 
                              (new_searches, user_id))
                conn.commit()
                conn.close()
                logger.info(f"🎉 Kullanıcı {user_id} 30 sorgu hakkı bonusu kazandı! Yeni hak: {new_searches}")
                return True
            
            conn.commit()
            conn.close()
            logger.info(f"✅ Kullanıcı {user_id} davet sayısı güncellendi: {new_invites}")
        
        return False
        
    except Exception as e:
        logger.error(f"❌ add_invite hatası: {e}")
        return False

# SQL dosyasını indirme ve işleme
def download_sql_file():
    sql_path = "eokul_data.sql"
    
    try:
        logger.info(f"📥 SQL dosyası indiriliyor: {DRIVE_URL}")
        
        gdown.download(DRIVE_URL, sql_path, quiet=False)
        
        if os.path.exists(sql_path) and os.path.getsize(sql_path) > 0:
            file_size = os.path.getsize(sql_path)
            logger.info(f"✅ SQL dosyası indirildi! Boyut: {file_size} bytes")
            return True
        else:
            logger.error("❌ SQL dosyası indirilemedi!")
            return False
            
    except Exception as e:
        logger.error(f"🚨 SQL indirme hatası: {e}")
        return False

def search_by_tc(tc_number):
    """TC'ye göre SQL dosyasında arama yap ve JSON döndür"""
    try:
        if not download_sql_file():
            return "SQL dosyası yüklenemedi"
        
        # SQL dosyasını oku
        with open('eokul_data.sql', 'r', encoding='utf-8') as f:
            sql_content = f.read()
        
        # TC'yi ara
        results = []
        lines = sql_content.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            # Python tuple formatını ara: (id, 'tc', ...)
            if f"'{tc_number}'" in line and line.startswith('(') and line.endswith('),'):
                # Satırı parse et
                clean_line = line[1:-2]  # Parantezleri ve virgülü kaldır
                values = [v.strip().strip("'") for v in clean_line.split(',')]
                
                if len(values) >= 6:
                    result = {
                        'id': values[0],
                        'tc_kimlik': values[1],
                        'okul_no': values[2],
                        'ad': values[3],
                        'soyad': values[4],
                        'durum': values[5]
                    }
                    results.append(result)
        
        logger.info(f"✅ {len(results)} kayıt bulundu, JSON formatında döndürülüyor")
        return results
        
    except Exception as e:
        logger.error(f"❌ Arama hatası: {e}")
        return f"Hata: {e}"

# Flask routes
@app.route('/')
def home():
    sql_loaded = os.path.exists('eokul_data.sql')
    return jsonify({
        "status": "active", 
        "message": "E-Okul Sorgulama Bot API",
        "sql_loaded": sql_loaded,
        "bot_type": "TC'den öğrenci bilgisi sorgulama",
        "drive_file_id": DRIVE_FILE_ID
    })

@app.route('/health')
def health():
    sql_status = download_sql_file()
    file_size = os.path.getsize('eokul_data.sql') if sql_status else 0
    
    return jsonify({
        "status": "healthy" if sql_status else "error",
        "sql_downloaded": sql_status,
        "sql_size": file_size,
        "results_format": "JSON"
    })

@app.route('/test-search/<tc>')
def test_search(tc):
    """Test için arama endpoint'i"""
    results = search_by_tc(tc)
    
    if isinstance(results, str):
        return jsonify({"error": results})
    
    return jsonify({
        "tc": tc,
        "result_count": len(results),
        "results": results,
        "format": "JSON"
    })

# Telegram Bot
def run_telegram_bot():
    try:
        BOT_TOKEN = os.getenv('BOT_TOKEN', '8370536277:AAGaB56GBjMUHsx5X0BS3_FXahtuPloLo6A')
        
        application = Application.builder().token(BOT_TOKEN).build()
        
        async def check_channel_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user_id = update.effective_user.id
            missing_channels = []
            
            for channel in REQUIRED_CHANNELS:
                try:
                    member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
                    if member.status not in ['member', 'administrator', 'creator']:
                        missing_channels.append(channel)
                except Exception as e:
                    missing_channels.append(channel)
            
            return missing_channels

        async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user_id = update.effective_user.id
            
            # Referans işlemi
            if context.args:
                try:
                    referrer_id = int(context.args[0])
                    if referrer_id != user_id:
                        bonus_verildi = add_invite(referrer_id)
                        if bonus_verildi:
                            await context.bot.send_message(
                                referrer_id,
                                "🎉 **TEBRİKLER! 3 KİŞİ DAVET ETTİNİZ!**\n\n"
                                "✅ **30 SORGU HAKKI** kazandınız!\n\n"
                                "@nabisystem @watronschecker"
                            )
                except ValueError:
                    pass
            
            # Kanal kontrolü
            missing_channels = await check_channel_membership(update, context)
            
            if missing_channels:
                buttons = []
                for channel in missing_channels:
                    buttons.append([InlineKeyboardButton(f"📢 {channel} Katıl", url=f"https://t.me/{channel[1:]}")])
                buttons.append([InlineKeyboardButton("✅ Kontrol Et", callback_data="check_membership")])
                reply_markup = InlineKeyboardMarkup(buttons)
                
                await update.message.reply_text(
                    "❌ **Kanal Üyeliği Gerekli**\n\n"
                    "Botu kullanmak için kanallara katılmanız gerekiyor!\n\n"
                    "Kanallara katıldıktan sonra '✅ Kontrol Et' butonuna tıklayın.",
                    reply_markup=reply_markup
                )
                return
            
            # Ana menü
            user_data = get_user_data(user_id)
            await update.message.reply_text(
                f"🎓 **E-Okul Sorgulama Botu**\n\n"
                f"**Kalan Sorgu Hakkı:** {user_data['remaining_searches']}\n"
                f"**Davet Edilen:** {user_data['invited_users']}/3 kişi\n"
                f"**Bonus Durumu:** {'✅ 30 HAK KAZANILDI' if user_data['bonus_received'] else '❌ 30 HAK BEKLİYOR'}\n\n"
                "**Komutlar:**\n"
                "• `/sorgu 12345678901` - TC'den öğrenci bilgisi\n"
                "• `/referans` - Davet linkini al\n\n"
                "🎉 **3 arkadaşını davet et, 30 SORGU HAKKI kazan!**\n\n"
                "@nabisystem @watronschecker"
            )

        async def sorgu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user_id = update.effective_user.id
            
            # Kanal kontrolü
            missing_channels = await check_channel_membership(update, context)
            if missing_channels:
                await update.message.reply_text("❌ Önce tüm kanallara katılmalısınız! /start")
                return
            
            user_data = get_user_data(user_id)
            
            if user_data['remaining_searches'] <= 0:
                await update.message.reply_text(
                    "❌ **Sorgu hakkınız kalmadı!**\n\n"
                    "Yeni hak kazanmak için 3 arkadaşınızı davet edin:\n"
                    "`/referans`\n\n"
                    "🎉 **3 davet = 30 SORGU HAKKI!**\n\n"
                    "@nabisystem @watronschecker"
                )
                return
            
            if not context.args:
                await update.message.reply_text("❌ **Doğru kullanım:** `/sorgu 12345678901`")
                return
            
            tc = context.args[0]
            
            if not tc.isdigit() or len(tc) != 11:
                await update.message.reply_text("❌ Geçersiz TC kimlik numarası! 11 haneli numara girin.")
                return
            
            # Hak sayısını güncelle
            update_user_searches(user_id, user_data['remaining_searches'] - 1)
            
            await update.message.reply_text("🔍 Öğrenci bilgileri aranıyor...")
            
            # Arama yap - SONUÇLAR JSON OLARAK GELİYOR
            sonuclar = search_by_tc(tc)
            
            if isinstance(sonuclar, str):
                await update.message.reply_text(f"❌ {sonuclar}")
                return
            
            if not sonuclar:
                await update.message.reply_text(f"❌ **{tc}** numarasına ait öğrenci bulunamadı.")
                return
            
            # JSON formatındaki sonuçları göster
            for i, kayit in enumerate(sonuclar[:5]):  # İlk 5 kaydı göster
                mesaj = (
                    f"**🎓 Öğrenci {i+1}:**\n"
                    f"**TC:** `{kayit['tc_kimlik']}`\n"
                    f"**Ad Soyad:** {kayit['ad']} {kayit['soyad']}\n"
                    f"**Okul No:** {kayit['okul_no']}\n"
                    f"**Durum:** {kayit['durum']}\n"
                    f"**Kayıt ID:** {kayit['id']}\n\n"
                    "📊 *JSON formatında* 📊\n"
                    "@nabisystem @watronschecker"
                )
                await update.message.reply_text(mesaj)
            
            # Kalan hakları göster
            user_data = get_user_data(user_id)
            await update.message.reply_text(
                f"✅ **Arama tamamlandı!**\n"
                f"**Kalan Sorgu Hakkı:** {user_data['remaining_searches']}\n"
                f"**Bulunan Kayıt:** {len(sonuclar)} adet\n"
                f"**Format:** JSON\n\n"
                "@nabisystem @watronschecker"
            )

        async def referans_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user_id = update.effective_user.id
            
            # Kanal kontrolü
            missing_channels = await check_channel_membership(update, context)
            if missing_channels:
                await update.message.reply_text("❌ Önce tüm kanallara katılmalısınız! /start")
                return
            
            user_data = get_user_data(user_id)
            
            bot_username = (await context.bot.get_me()).username
            invite_link = f"https://t.me/{bot_username}?start={user_id}"
            
            # Davet durumuna göre mesaj
            if user_data['bonus_received']:
                bonus_text = "✅ **30 SORGU HAKKI ZATEN KAZANILDI!**"
                info_text = "🎉 Bonusu zaten aldınız! Yeni davetler için teşekkürler."
            elif user_data['invited_users'] >= 3:
                bonus_text = "✅ **30 SORGU HAKKI HAK EDİLDİ!**"
                info_text = "🎉 3 kişi davet ettiniz! Bonus otomatik olarak eklendi."
            else:
                kalan = 3 - user_data['invited_users']
                bonus_text = f"❌ **{kalan} kişi kaldı!**"
                info_text = f"🔥 {kalan} kişi daha davet ederek 30 SORGU HAKKI kazan!"
            
            await update.message.reply_text(
                f"📨 **REFERANS SİSTEMİ**\n\n"
                f"**Davet Durumu:** {user_data['invited_users']}/3 kişi\n"
                f"**Toplam Davet:** {user_data['total_invites']} kişi\n"
                f"**Bonus:** {bonus_text}\n\n"
                f"{info_text}\n\n"
                f"**Davet Linkiniz:**\n`{invite_link}`\n\n"
                "📍 **Nasıl Çalışır?**\n"
                "1. Linki arkadaşlarınıza gönderin\n"
                "2. Onlar botu kullanmaya başlasın\n"
                "3. 3 kişi tamamlayınca 30 HAK kazanın!\n\n"
                "@nabisystem @watronschecker"
            )

        async def check_membership_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
            query = update.callback_query
            await query.answer()
            
            missing_channels = await check_channel_membership(update, context)
            
            if not missing_channels:
                await query.edit_message_text("✅ **Tüm kanallara katılım onaylandı!**\n\nBotu kullanmaya başlayabilirsiniz.")
                await start_command(update, context)
            else:
                await query.edit_message_text("❌ **Hala kanallara katılmadınız!** Lütfen /start komutu ile tekrar deneyin.")

        # Handlers
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("sorgu", sorgu_command))
        application.add_handler(CommandHandler("referans", referans_command))
        application.add_handler(CallbackQueryHandler(check_membership_callback, pattern="check_membership"))
        
        logger.info("🤖 E-Okul Bot başlatılıyor...")
        application.run_polling()
        
    except Exception as e:
        logger.error(f"❌ Bot hatası: {e}")

# Uygulamayı başlat
if __name__ == '__main__':
    # Database'i başlat
    init_db()
    
    # SQL dosyasını önceden indir
    logger.info("📥 SQL dosyası indiriliyor...")
    download_sql_file()
    
    # Bot'u thread'te başlat
    bot_thread = threading.Thread(target=run_telegram_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    # Flask'ı başlat
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🌐 Flask API başlatılıyor: port {port}")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
