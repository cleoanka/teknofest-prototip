# Model Eğitim / Fine-Tune Sistemi

Elimizde eğitilmiş özel model yok. Strateji (transkriptteki komite onayına uygun):
**COCO ön-eğitimli ağırlıklardan başla → açık kaynak setlerle genişlet → komite
TOGG/etiketli verisi gelince fine-tune et.**

## Adımlar

1. **Veri topla / hazırla**
   ```bash
   # Komite senaryo videolarından kare çıkar
   python -m ai.training.prepare_dataset frames --video ornek.mp4 --out datasets/raw --fps 2
   # YOLO klasör iskeleti
   python -m ai.training.prepare_dataset scaffold --root datasets/yolguvenligi
   ```
   Etiketleme: Roboflow / CVAT / labelImg (YOLO formatı). Sınıflar `data.yaml` ile aynı.

2. **Açık kaynak köprü** (opsiyonel, genelleme için)
   - vehicle/person/phone → COCO + BDD100K
   - license_plate → CCPD / OpenALPR / TR plaka setleri
   - cigarette/seatbelt/headphone → küçük özel etiketleme + augmentation

3. **Eğit**
   ```bash
   python -m ai.training.train --data ai/training/data.yaml --base yolov8s.pt \
       --epochs 80 --imgsz 640 --device auto --export-int8
   ```

4. **Devreye al**
   `runs/detect/yolguvenligi*/weights/best.pt` → `.env` içinde
   `YOLO_MODEL_CRITICAL=.../best.pt` yap. Sistem otomatik bu modeli kullanır.

## Tasarım notları (rapora hazır)
- **Doğruluk/gecikme dengesi:** Normal modda `yolov8n`, kritik modda `yolov8s`.
  INT8 export ile ~%20-35 gecikme azalması, <1.5 mAP kaybı (NVIDIA TensorRT).
- **Genelleme:** mozaik + renk jitter + gece/yağmur sentetik augmentation; test
  setinde farklı araç/açı/hava olacağı için (transkript) zorunlu.
- **Nadir sınıf dengesizliği:** yorgunluk/kaza nadir → `cls` ağırlığı + focal etkisi.
- **Değerlendirme:** `python -m eval.evaluate` Normal vs Kritik doğruluk farkını
  ölçer (QoD'nin %40'lık kriterini kanıtlar).
