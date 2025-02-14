import os
import zipfile
import fitz  # PyMuPDF
from pdf2image import convert_from_path
from PIL import Image, ImageChops
from pyrogram import Client, filters
import logging

# Логирование для диагностики в облаке
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Настройки бота через переменные окружения
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Проверяем наличие переменных окружения
if not (API_ID and API_HASH and BOT_TOKEN):
    raise ValueError("API_ID, API_HASH и BOT_TOKEN должны быть установлены в переменных окружения")

# Создаём клиента Pyrogram
bot = Client("kaspi_waybill_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Пути для работы
WORK_DIR = "downloads"
EXTRACT_DIR = os.path.join(WORK_DIR, "extracted")
OUTPUT_PDF = os.path.join(WORK_DIR, "merged_output.pdf")

os.makedirs(WORK_DIR, exist_ok=True)
os.makedirs(EXTRACT_DIR, exist_ok=True)

# Функция для разрезания листа на 4 части и удаления пустых областей
def split_and_clean_page(image):
    width, height = image.size
    quadrants = [
        image.crop((0, 0, width // 2, height // 2)),
        image.crop((width // 2, 0, width, height // 2)),
        image.crop((0, height // 2, width // 2, height)),
        image.crop((width // 2, height // 2, width, height))
    ]

    def trim(im):
        bg = Image.new("RGB", im.size, "white")
        diff = ImageChops.difference(im, bg)
        return im.crop(diff.getbbox()) if diff.getbbox() else None

    return [trim(quad) for quad in quadrants if trim(quad) is not None]

# Функция для объединения накладных по 4 на одном листе A4
def merge_to_a4(waybills):
    A4_SIZE = (2480, 3508)  # Размер A4 в пикселях при 300 DPI
    PADDING = 60
    QUAD_WIDTH = (A4_SIZE[0] - 3 * PADDING) // 2
    QUAD_HEIGHT = (A4_SIZE[1] - 3 * PADDING) // 2
    pages = []
    current_page = Image.new("RGB", A4_SIZE, "white")
    count = 0

    for waybill in waybills:
        waybill = waybill.resize((QUAD_WIDTH, QUAD_HEIGHT))
        x_offset = (count % 2) * (QUAD_WIDTH + PADDING) + PADDING
        y_offset = (count // 2) * (QUAD_HEIGHT + PADDING) + PADDING
        current_page.paste(waybill, (x_offset, y_offset))
        count += 1

        if count == 4:
            pages.append(current_page)
            current_page = Image.new("RGB", A4_SIZE, "white")
            count = 0

    if count > 0:
        pages.append(current_page)

    return pages

# Функция обработки ZIP-файла с накладными
def process_zip(zip_path):
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(EXTRACT_DIR)

    pdf_files = [os.path.join(EXTRACT_DIR, f) for f in sorted(os.listdir(EXTRACT_DIR)) if f.endswith(".pdf")]
    extracted_waybills = []

    for pdf in pdf_files:
        images = convert_from_path(pdf, dpi=300)
        for image in images:
            extracted_waybills.extend(split_and_clean_page(image))

    final_pages = merge_to_a4(extracted_waybills)

    if final_pages:
        final_pages[0].save(OUTPUT_PDF, save_all=True, append_images=final_pages[1:])
        return OUTPUT_PDF
    else:
        raise ValueError("Не удалось создать PDF - пустой список страниц")

# Обработка загруженного ZIP-файла
@bot.on_message(filters.document & filters.private)
def handle_zip(client, message):
    logger.info("Получен ZIP-файл: %s", message.document.file_name)
    file_path = os.path.join(WORK_DIR, message.document.file_name)
    message.download(file_path)

    try:
        final_pdf = process_zip(file_path)
        message.reply_document(final_pdf, caption="Готовый файл с объединёнными накладными")
    except Exception as e:
        logger.error("Ошибка при обработке файла: %s", e)
        message.reply_text(f"Ошибка при обработке файла: {e}")

    os.remove(file_path)
    for file in os.listdir(EXTRACT_DIR):
        os.remove(os.path.join(EXTRACT_DIR, file))

# Запуск бота
logger.info("Бот запущен...")
bot.run()
