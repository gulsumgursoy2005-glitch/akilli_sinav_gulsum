# AI Destekli Akıllı Sınav Hazırlama Sistemi

Bu proje, kullanıcıdan konu adı, soru sayısı ve zorluk seviyesini alan, Gemini API ile özet, test soruları, cevap anahtarı, klasik sorular ve çalışma önerisi üreten bir Streamlit uygulamasıdır.

## Özellikler

- Streamlit arayüzü ile konu girişi
- Soru sayısı ve zorluk seviyesi seçimi
- Gemini API ile JSON tabanlı sınav üretimi
- SQLite ile sınav geçmişi kaydı
- CSV olarak dışa aktarma
- Cevap anahtarını göster/gizle seçeneği

## Kurulum

1. Gerekli paketleri kurun:
   ```bash
   pip install -r requirements.txt
   ```
2. `.env.example` dosyasını `.env` olarak kopyalayın ve Gemini API anahtarınızı ekleyin.
3. Uygulamayı çalıştırın:
   ```bash
   streamlit run app.py
   ```

## Dosya Yapısı

- `app.py` – ana uygulama
- `requirements.txt` – Python bağımlılıkları
- `.env.example` – ortam değişkenleri örneği

## Not

Gemini API anahtarı olmadan uygulama çalışmaz. API anahtarınızı `.env` dosyasına ekleyin.
