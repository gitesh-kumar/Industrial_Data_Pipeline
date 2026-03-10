# 🏭 Industrial IoT: Predictive Maintenance & Financial Lakehouse

This project is a **Full-Stack Data Engineering Pipeline** designed to monitor factory machinery in real-time. It translates raw mechanical telemetry (vibration and temperature) into **Real-Time Financial Risk** by correlating sensor anomalies with live energy market costs.



## 🛠️ System Architecture (Medallion)
The pipeline follows a modular **Medallion Architecture** to ensure data quality and lineage:

* **Bronze Layer (Ingestion):** Multi-threaded simulation of IoT sensors (Compressors, Pumps, Turbines) capturing high-frequency telemetry.
* **Silver Layer (Transformation):** Data cleaning and validation. Includes a **Quality Gate** to detect "Sensor Drift" and handle null values using industrial standards.
* **Gold Layer (Analytics):** High-level business logic. Integrates an **External API** for energy pricing to calculate the `estimated_hourly_loss_euro`.
* **Governance & Audit:** Automated health checks that generate a "Pipeline Health Score" to ensure data integrity for downstream stakeholders.



## 🚀 Key Features
* **End-to-End Orchestration:** Fully automated lifecycle via `main.py`.
* **Idempotent ETL:** SQL-based logic ensures no duplicate records, maintaining a "Single Source of Truth."
* **Executive BI Dashboard:** A Power BI "Command Center" featuring conditional formatting (Heatmaps) for immediate OPEX risk identification.
* **Scalable Design:** Architected to be easily ported from local SQLite to cloud-scale (Azure Synapse/AWS Redshift).

## 🧰 Tech Stack
* **Language:** Python 3.12+ (Pandas, SQLAlchemy, Requests)
* **Database:** SQLite (Relational Data Lakehouse)
* **BI Tool:** Power BI Desktop
* **Version Control:** Git

## ⚙️ How to Run
1.  **Clone the repository:**
    ```bash
    git clone [https://github.com/gitesh-kumar/Industrial_Data_Pipeline.git](https://github.com/gitesh-kumar/Industrial_Data_Pipeline.git)
    ```
2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
3.  **Execute the pipeline:**
    ```bash
    python main.py
    ```

