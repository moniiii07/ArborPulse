# ArborPulse own-model workflow

ArborPulse trains a Random Forest forest-loss screening classifier inside Google Earth Engine.

- **Training labels:** Hansen Global Forest Change `lossyear` for 2023.
- **Inputs:** Sentinel-2 B2, B3, B4, B8, B11, and B12 change, plus NDVI and NBR change between January–March and July–September composites.
- **Class balancing:** Equal-size loss and no-loss strata are sampled so the classifier does not learn to predict only no loss.
- **Evaluation:** The western half of the training region is used for training and the eastern half is held out. This geographic hold-out is more honest than randomly splitting nearby pixels.
- **Output:** A 2025 map of predicted-loss review pixels for the Rondônia pilot area.

## Important interpretation

This is a custom **screening** model. Its metrics show agreement with held-out Hansen labels, because Hansen supplies the training labels. They are not independent proof of deforestation. Do not also call Hansen an independent validation of this model.

Run `scripts/train_loss_classifier.js` in the Earth Engine Code Editor. Record the printed confusion matrix, precision, recall, F1, and sample counts in the project presentation.
