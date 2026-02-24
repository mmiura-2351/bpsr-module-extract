# モジュールOCRツール 内部設計仕様 v1.1

本書は「機能仕様 v1.1（JSONスキーマ確定版）」を実装するための内部設計を定義する。

## 1. 設計方針

- 内部データは `effect_id` を正とする。
- OCR文字列は補助情報として扱い、永続化対象は `effect_id + value` のみ。
- GUI とドメインロジックを分離し、OCR処理は非同期実行する。
- 出力JSONは常に `schema = "bpsr-module-calculator/modules"`、`version = 1` を満たす。

## 2. 推奨ディレクトリ構成

```text
module_ocr_tool/
  main.py
  app/
    controller.py
    state.py
    models.py
    mappings.py
    normalizer.py
    ocr_engine.py
    capture.py
    exporter.py
    ui/
      main_window.py
      result_dialog.py
  tests/
    test_normalizer.py
    test_exporter.py
```

## 3. データモデル設計

## 3.1 Domain Model

```python
from dataclasses import dataclass, field

@dataclass
class EffectEntry:
    effect_id: str
    value: int

@dataclass
class ModuleRecord:
    module_category: str = "general"
    effects: list[EffectEntry] = field(default_factory=list)
```

制約:

- `module_category` は固定で `"general"`。
- `effects` は 0〜3 件。
- `value` は整数。OCR抽出時は `+` 記号を除去して保存する。

## 3.2 App State

`app/state.py` に状態管理用データを集約する。

```python
@dataclass
class AppState:
    status: str  # idle / waiting_capture / processing / editing_result / error
    modules: list[ModuleRecord]
    last_raw_ocr_text: str | None = None
    last_error_message: str | None = None
```

## 4. マッピング設計

`app/mappings.py` に日本語ラベルと `effect_id` の双方向マップを定義する。

```python
JP_TO_EFFECT_ID = {
    "集中・詠唱": "cast_focus",
    "集中・会心": "crit_focus",
    "集中・幸運": "luck_focus",
    "集中・攻撃速度": "attack_spd",
    "極・HP変動": "extreme_life_wave",
    "極・HP吸収": "extreme_life_steal",
    "極・幸運会心": "extreme_team_luck_crit",
    "筋力強化": "strength_boost",
    "敏捷強化": "agility_boost",
    "知力強化": "intellect_boost",
    "特攻ダメージ強化": "special_attack",
    "精鋭打撃": "elite_strike",
    "極・ダメージ増強": "extreme_dmg_stack",
    "極・適応力": "extreme_agile",
    "特攻回復強化": "healing_boost",
    "マスタリー回復強化": "healing_enhance",
    "極・HP凝縮": "extreme_life_condense",
    "極・応急処置": "extreme_first_aid",
    "魔法耐性": "resistance",
    "物理耐性": "armor",
    "極・絶境守護": "extreme_final_protection",
}
```

派生定義:

- `EFFECT_ID_TO_JP = {v: k for k, v in JP_TO_EFFECT_ID.items()}`
- 候補提示順は `JP_TO_EFFECT_ID` の定義順を採用。

## 5. OCRパイプライン設計

## 5.1 処理レイヤ

1. `capture.py`: `mss` でスクリーンショット取得（全画面または指定領域）
1. `ocr_engine.py`: OpenCV 前処理 + Tesseract 実行
1. `normalizer.py`: OCR文字列を `EffectEntry` に正規化
1. `result_dialog.py`: 補正UI（候補選択 / `effect_id` 直接編集）

## 5.2 OCR前処理（OpenCV）

推奨処理:

1. グレースケール化
1. 2値化（Otsu）
1. ノイズ除去（median blur）
1. 必要時のみリサイズ（1.5〜2.0倍）

Tesseract設定例:

- `lang="jpn"`
- `--oem 3 --psm 6`

## 5.3 正規化ロジック

入力行例:

- `集中・攻撃速度+4`
- `集中・攻事速度+4`（OCR誤認）

抽出手順:

1. 行分割して空行を除去
1. 正規表現で数値抽出: `([+-]?\d+)`（`+4` -> `4`）
1. 数値除去後の文字列を効果名候補としてトリム
1. 完全一致で `JP_TO_EFFECT_ID` を検索
1. 不一致時は曖昧一致（`difflib.get_close_matches`）で候補上位N件を返す

`normalizer.py` の戻り値:

```python
@dataclass
class ParsedEffectCandidate:
    raw_line: str
    parsed_value: int | None
    resolved_effect_id: str | None
    jp_label_candidates: list[str]
```

確定条件:

- `parsed_value` が整数
- `resolved_effect_id` が存在

確定不可は GUI で手動修正可能にする。

## 6. GUI状態遷移設計

## 6.1 主要状態

- `idle`: 起動直後
- `waiting_capture`: F8待機
- `processing`: キャプチャ/OCR/正規化中
- `editing_result`: OCR結果確認・修正中
- `error`: 復旧可能エラー表示中

## 6.2 状態遷移

```text
idle
  └─ [処理開始] -> waiting_capture

waiting_capture
  ├─ [F8] -> processing
  └─ [ESC] -> idle

processing
  ├─ [成功] -> editing_result
  └─ [失敗] -> error

editing_result
  ├─ [確定] -> waiting_capture  (ModuleRecord追加)
  └─ [キャンセル] -> waiting_capture (追加なし)

error
  ├─ [再試行] -> waiting_capture
  └─ [閉じる] -> idle
```

## 6.3 UIコンポーネント責務

- `MainWindow`
  - `[処理開始]`, `[JSON出力]` ボタン
  - 状態表示、取得モジュール数表示
- `ResultDialog`
  - OCR候補一覧表示
  - `effect_id` 直接編集欄
  - `value` 入力欄
  - `[確定]` / `[キャンセル]`

## 7. コントローラ設計

`controller.py` の中核クラス:

```python
class AppController:
    def start_capture_mode(self) -> None: ...
    def on_hotkey_f8(self) -> None: ...
    def process_capture(self) -> list[ParsedEffectCandidate]: ...
    def confirm_module(self, effects: list[EffectEntry]) -> None: ...
    def export_json(self, output_path: str) -> None: ...
```

ポイント:

- F8ハンドラは GUI スレッドをブロックしない（`threading.Thread` で `process_capture` 実行）。
- UI更新は `tk.after()` 経由でメインスレッドに戻す。
- `confirm_module` で `effects` 件数を 3 件以下に強制する。

## 8. JSON出力設計

`exporter.py`:

```python
def build_export_payload(modules: list[ModuleRecord]) -> dict: ...
def write_export_json(payload: dict, output_path: str) -> None: ...
```

生成仕様:

- `exported_at = datetime.utcnow().isoformat() + "Z"`
- `modules` は `ModuleRecord` を辞書化して出力

出力例:

```json
{
  "schema": "bpsr-module-calculator/modules",
  "version": 1,
  "exported_at": "2026-02-23T15:28:00.609Z",
  "modules": [
    {
      "module_category": "general",
      "effects": [
        {"effect_id": "attack_spd", "value": 4},
        {"effect_id": "cast_focus", "value": 9},
        {"effect_id": "luck_focus", "value": 5}
      ]
    }
  ]
}
```

## 9. 例外/失敗時設計

- OCR結果 0件: `ResultDialog` で空行手動入力を許可
- 効果名不明: 候補提示 + `effect_id` 直接入力を許可
- 数値不正: 赤字バリデーションで確定不可
- JSON出力失敗: エラーダイアログに例外メッセージ表示

## 10. テスト設計（最低限）

`tests/test_normalizer.py`

- 正常系: `集中・攻撃速度+4` -> `attack_spd, 4`
- OCR誤認系: `集中・攻事速度+4` -> 候補に `集中・攻撃速度`
- 数値欠損: `集中・詠唱` -> `parsed_value is None`
- 上限超過: 4行入力時に 3件へ制限

`tests/test_exporter.py`

- `schema/version` 固定値検証
- `exported_at` が UTC ISO8601 + `Z` 形式
- `module_category` 固定値検証

## 11. 実装順序（推奨）

1. `mappings.py`, `models.py` 実装
1. `normalizer.py` 単体テスト先行
1. `exporter.py` 実装
1. `ocr_engine.py` + `capture.py` 実装
1. `ui/` + `controller.py` を接続
1. ホットキー統合とE2E動作確認
