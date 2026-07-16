# AI타임스 기사목록 수집기 (EDCF 주간픽용)

매주 월요일 오전 8시(KST), AI타임스 전체기사 목록에서 최근 10일치
제목·게재일·URL·리드문을 수집해 `articles.md`로 저장합니다.

- 비용: **0원** (API 키·Gmail·Secrets 전부 불필요)
- 수집만 하고 요약은 안 함 → 요약·선별은 Claude 채팅에서

## 셋업 (1회, 5분)

1. GitHub에서 새 **public** 저장소 생성 (예: `aitimes-collector`)
   - public이어야 Claude가 결과 파일을 읽을 수 있음. 기사 제목·링크만 담기므로 공개해도 무방.
2. 이 폴더의 파일 3개를 저장소에 업로드
   - `collect.py`, `README.md`, `.github/workflows/collect.yml` (경로 그대로)
3. 저장소 → Actions 탭 → "Collect AITimes Articles" → **Run workflow** 로 1회 테스트
4. 1~2분 뒤 저장소에 `articles.md` 가 생기면 성공

## Claude에게 알려줄 주소

테스트 성공 후, 아래 형태의 주소를 Claude 채팅에 알려주세요.
(USERNAME/저장소명만 본인 것으로)

```
https://raw.githubusercontent.com/USERNAME/aitimes-collector/main/articles.md
```

Claude가 이 주소를 주간픽 수집 소스로 기억해두고, 매주 "주간픽" 한 마디에
이 파일을 읽어 선별·요약합니다.

## 주간 루틴

1. (자동) 월요일 08:00 수집 실행
2. Claude 채팅: "주간픽" → 선별·요약 생성
3. 결과를 '메일 서식 변환기' 아티팩트에 붙여넣기 → 검토 → 메일용 서식 복사 → 발송
