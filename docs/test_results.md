# Weapon Detection Test Results

| Video | Duration | Weapon type | Person detected | Weapon detected | Conf | FPs |
|-------|----------|-------------|-----------------|-----------------|------|-----|
| sample_gun.mp4 | 15s | Pistol | Yes | Yes | 0.81 | 0 |
| sample_knife.mp4 | 12s | Knife | Yes | Yes | 0.88 | 0 |

## Failure Cases

- **Low light**: When lighting conditions drop below operational thresholds, the lack of contrast causes detection to fail.
- **Weapon partially hidden**: Extreme occlusion, such as when a weapon is mostly concealed by clothing or objects, prevents the model from capturing sufficient features, resulting in a detection failure.
