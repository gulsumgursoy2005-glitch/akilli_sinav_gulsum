import csv
import io
import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

try:
    import google.generativeai as genai
    from google.generativeai import types
except ImportError:  # pragma: no cover - import guard
    genai = None
    types = None

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "sinavlar.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


st.set_page_config(page_title="AI Sınav Hazırlayıcı", page_icon="🧠", layout="wide")


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sinavlar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            konu TEXT NOT NULL,
            tarih TEXT NOT NULL,
            soru_sayisi INTEGER NOT NULL,
            zorluk TEXT NOT NULL,
            olusturulan_sinav TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def save_exam(konu: str, soru_sayisi: int, zorluk: str, content: dict) -> None:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        INSERT INTO sinavlar (konu, tarih, soru_sayisi, zorluk, olusturulan_sinav)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            konu.strip(),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            soru_sayisi,
            zorluk,
            json.dumps(content, ensure_ascii=False),
        ),
    )
    conn.commit()
    conn.close()


def load_history(search_term: str = "") -> list[dict]:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    if search_term.strip():
        rows = conn.execute(
            "SELECT id, konu, tarih, soru_sayisi, zorluk, olusturulan_sinav FROM sinavlar WHERE konu LIKE ? ORDER BY id DESC",
            (f"%{search_term}%",),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, konu, tarih, soru_sayisi, zorluk, olusturulan_sinav FROM sinavlar ORDER BY id DESC"
        ).fetchall()
    conn.close()
    return [
        {
            "id": row[0],
            "konu": row[1],
            "tarih": row[2],
            "soru_sayisi": row[3],
            "zorluk": row[4],
            "olusturulan_sinav": json.loads(row[5]),
        }
        for row in rows
    ]


def parse_json_response(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.MULTILINE)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)


def normalize_exam_payload(payload: dict, soru_sayisi: int) -> dict:
    normalized = {
        "ozet": payload.get("ozet", "Özet oluşturulamadı."),
        "test_sorulari": [],
        "klasik_sorular": payload.get("klasik_sorular", [])[:5],
        "calisma_onerisi": payload.get("calisma_onerisi", "Daha fazla tekrar yapın."),
    }

    for item in payload.get("test_sorulari", [])[:soru_sayisi]:
        options = item.get("secenekler", [])
        if len(options) != 4:
            options = ["A", "B", "C", "D"]
        normalized["test_sorulari"].append(
            {
                "soru": item.get("soru", "Soru metni bulunamadı."),
                "secenekler": options,
                "dogru": item.get("dogru", "A"),
            }
        )

    while len(normalized["test_sorulari"]) < soru_sayisi:
        normalized["test_sorulari"].append(
            {
                "soru": f"Ek soru {len(normalized['test_sorulari']) + 1}",
                "secenekler": ["A", "B", "C", "D"],
                "dogru": "A",
            }
        )

    return normalized


def generate_exam(konu: str, soru_sayisi: int, zorluk: str, provider: str) -> dict:
    prompt = f"""
    Konu: '{konu}'.
    Zorluk: '{zorluk}'.
    Şu JSON şemasına uygun içerik üret:
    {{
      "ozet": "kısa paragraf",
      "test_sorulari": [
        {{"soru": "string", "secenekler": ["A", "B", "C", "D"], "dogru": "A"}}
      ],
      "klasik_sorular": ["string", "string", "string", "string", "string"],
      "calisma_onerisi": "kısa uygulamaya dönük öneri"
    }}
    {soru_sayisi} adet test sorusu üret. 5 adet klasik soru ekle.
    Çıktıyı yalnızca geçerli JSON olarak ver. Türkçe yaz.
    """

    if provider == "groq":
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY bulunamadı. Lütfen .env dosyasına ekleyin.")
        model_name = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.4,
        }
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=120)
            response.raise_for_status()
            data = response.json()
            raw_text = data["choices"][0]["message"]["content"]
        except Exception as exc:
            error_text = str(exc)
            if "401" in error_text or "invalid_api_key" in error_text.lower():
                raise RuntimeError("Groq API anahtarı geçersiz veya kabul edilmedi. Anahtarınızı kontrol edin.") from exc
            raise RuntimeError(f"Groq API çağrısı başarısız: {error_text}") from exc
        payload_json = parse_json_response(raw_text)
        return normalize_exam_payload(payload_json, soru_sayisi)

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY bulunamadı. Lütfen .env dosyasına ekleyin.")
    if genai is None or types is None:
        raise RuntimeError("google-generativeai paketi kurulu değil. requirements.txt üzerinden kurulum yapın.")

    genai.configure(api_key=api_key)
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    model = genai.GenerativeModel(model_name)

    generation_config = types.GenerationConfig(
        temperature=0.4,
        response_mime_type="application/json",
    )
    try:
        response = model.generate_content(prompt, generation_config=generation_config)
    except Exception as exc:
        error_text = str(exc)
        if "429" in error_text or "quota" in error_text.lower() or "ResourceExhausted" in error_text:
            raise RuntimeError("Gemini API kotası dolu veya sınırlı. Bir süre bekleyip tekrar deneyin.") from exc
        if "404" in error_text or "not found" in error_text.lower():
            raise RuntimeError(f"Gemini model adı geçersiz: {model_name}. .env dosyasındaki GEMINI_MODEL değerini değiştirin.") from exc
        raise RuntimeError(f"Gemini API çağrısı başarısız: {error_text}") from exc

    raw_text = getattr(response, "text", "") or ""
    if not raw_text:
        raise RuntimeError("Model boş çıktı döndürdü.")
    payload = parse_json_response(raw_text)
    return normalize_exam_payload(payload, soru_sayisi)


def build_csv(exam: dict) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Tip", "İçerik", "Detay"])
    writer.writerow(["Özet", exam.get("ozet", "")])
    for idx, soru in enumerate(exam.get("test_sorulari", []), start=1):
        writer.writerow([f"Soru {idx}", soru.get("soru", ""), " | ".join(soru.get("secenekler", []))])
        writer.writerow(["Doğru cevap", "", soru.get("dogru", "")])
    writer.writerow(["Çalışma önerisi", exam.get("calisma_onerisi", "")])
    return output.getvalue()


def render_exam(exam: dict, konu: str, soru_sayisi: int, zorluk: str) -> None:
    st.success("Sınav başarıyla hazırlandı.")
    col1, col2 = st.columns([2, 1])
    with col1:
        st.subheader(f"Konu: {konu}")
    with col2:
        st.caption(f"Soru sayısı: {soru_sayisi} | Zorluk: {zorluk}")

    st.download_button(
        label="CSV olarak indir",
        data=build_csv(exam),
        file_name=f"{konu.lower().replace(' ', '_')}_sinavi.csv",
        mime="text/csv",
    )

    with st.expander("Konu Özeti", expanded=True):
        st.write(exam.get("ozet", ""))

    with st.expander("Test Soruları", expanded=True):
        for idx, soru in enumerate(exam.get("test_sorulari", []), start=1):
            st.markdown(f"**{idx}. {soru.get('soru', '')}**")
            for option in soru.get("secenekler", []):
                st.write(f"- {option}")
            st.write("")

    show_answers = st.checkbox("Cevap anahtarını göster")
    if show_answers:
        with st.expander("Cevap Anahtarı", expanded=True):
            for idx, soru in enumerate(exam.get("test_sorulari", []), start=1):
                st.write(f"{idx}. {soru.get('dogru', '')}")

    with st.expander("Klasik Sorular", expanded=True):
        for idx, soru in enumerate(exam.get("klasik_sorular", []), start=1):
            st.write(f"{idx}. {soru}")

    with st.expander("Çalışma Tavsiyesi", expanded=True):
        st.write(exam.get("calisma_onerisi", ""))


def render_history_panel() -> None:
    st.sidebar.markdown("### Geçmiş Sınavlar")
    search_term = st.sidebar.text_input("Ara", placeholder="Konu adı girin")
    history = load_history(search_term)
    if not history:
        st.sidebar.info("Henüz kayıt yok.")
        return

    selected = st.sidebar.selectbox(
        "Bir sınav seçin",
        options=[(item["id"], item["konu"], item["tarih"]) for item in history],
        format_func=lambda item: f"{item[1]} — {item[2]}",
    )
    if selected:
        selected_id = selected[0]
        selected_exam = next(item for item in history if item["id"] == selected_id)
        with st.sidebar.expander("Seçilen sınav", expanded=True):
            st.write(selected_exam["konu"])
            st.write(selected_exam["tarih"])
            st.write(selected_exam["zorluk"])
            st.write(selected_exam["soru_sayisi"])


def main() -> None:
    init_db()
    st.title("AI Sınav Hazırlayıcı")
    st.caption("Konu adı girin, soru sayısını seçin, zorluk seviyesini ayarlayın ve tercih ettiğiniz AI sağlayıcısıyla sınav hazırlayın.")

    render_history_panel()

    with st.form("exam_form"):
        konu = st.text_input("Konu adı", placeholder="Örn. Python Döngüler")
        soru_sayisi = st.slider("Soru sayısı", min_value=3, max_value=15, value=5)
        zorluk = st.radio("Zorluk", ["Kolay", "Orta", "Zor"], horizontal=True)
        provider = st.radio("AI Sağlayıcı", ["gemini", "groq"], horizontal=True, index=0)
        submitted = st.form_submit_button("Hazırla")

    if submitted:
        if not konu.strip():
            st.error("Lütfen konu adını girin.")
            return

        try:
            provider_label = "Gemini" if provider == "gemini" else "Groq"
            with st.spinner(f"{provider_label} modeli sınavı hazırlıyor..."):
                exam = generate_exam(konu, soru_sayisi, zorluk, provider)
            save_exam(konu, soru_sayisi, zorluk, exam)
            render_exam(exam, konu, soru_sayisi, zorluk)
        except Exception as exc:  # pragma: no cover - runtime path
            st.error(f"Bir hata oluştu: {exc}")
            st.info("API anahtarını .env dosyasına eklediğinizden emin olun. Örnek: GEMINI_API_KEY=your_key veya GROQ_API_KEY=your_key")


if __name__ == "__main__":
    main()
