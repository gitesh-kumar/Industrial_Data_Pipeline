# 🏭 Private Industrial Data AI Pipeline

A local-first, privacy-compliant data engineering pipeline designed for **Industrie 4.0** environments.

## 🌟 Project Overview
This project demonstrates a full-stack Data Engineering solution that processes raw factory sensor data into actionable financial insights. The unique value proposition is the **Data Sovereignty**—using a local LLM (Llama 3) to query sensitive KPIs without ever sending data to a cloud provider (OpenAI/Google).



## 🛠️ Architecture: The Medallion Pattern
The pipeline follows the industry-standard **Medallion Architecture**:
- **Bronze (Raw):** Ingestion of raw sensor CSVs (Temperature, Vibration, Power).
- **Silver (Cleaned):** Data validation, unit conversion (F to C), and quality flagging.
- **Gold (Business):** Aggregated financial impact analysis (Estimated Hourly Loss in €).

## 🧠 AI Agent: "The Plant Manager"
Instead of a simple chatbot, this project uses a **ReAct (Reason/Act) SQL Agent**:
- **Framework:** LangChain
- **Inference:** Local Llama 3 via **Ollama**
- **Logic:** The agent autonomously writes and executes SQL queries against the Gold Layer to answer complex questions like: *"What is the percentage of loss of the highest-loss machine relative to the total?"*

## 🚀 Key Professional Features
- **Python 3.12 Optimized:** Migrated from 3.8 to 3.12 with modern type hinting.
- **Local Inference:** 100% offline. No API keys or external data leaks.
- **Robust Error Handling:** Implemented ReAct loops to handle complex multi-step analytical queries.

## 📈 Sample AI Query
**User:** *"Which machine should I repair first based on hourly loss?"* **AI:** *"You should prioritize COMPRESSOR_03, which accounts for 63.14% of the total factory hourly loss (€19.58/hr)."*

## ⚙️ Setup
1. Install [Ollama](https://ollama.com) and run `ollama run llama3`.
2. `pip install -r requirements.txt`
3. Run `python main.py` to populate the Lakehouse.
4. Run `python ai_assistant.py` to talk to the factory.
