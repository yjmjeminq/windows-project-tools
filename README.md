# 유희왕 Link Evolution 개발

스위치 1.0.1용 2배속 패치와 카드 이식 도구, Windows판 덱 선택 수정 소스, PC 카드 모드의 정의와 설정을 담습니다. 추가 카드 데이터는 스위치판의 카드 등록·저장·효과 코드 작업을 거쳐야 실제 듀얼에서 쓸 수 있습니다.

## 다른 PC에서 이어서 작업하기

1. 각 PC에서 `git clone https://github.com/yjmjeminq/YGO-PC-Full.git`으로 저장소를 복제합니다. 복제한 폴더에서 작업을 시작할 때 `git pull --ff-only`로 최신 커밋을 가져옵니다.
2. 스위치 1.0.1에서 추출한 `ExeFS/main`과 `RomFS`를 `Switch-Port/1.0.1` 아래에 둡니다. 카드 데이터 빌드에는 각 `cards.json`의 `image` 경로에 해당하는 로컬 이미지도 필요합니다.
3. 수정한 소스와 카드 정의를 커밋한 뒤 `git push` 합니다. 다른 PC에서 같은 원격 저장소를 가져오면 수정분을 이어서 작업할 수 있습니다.

게임 본편·업데이트 NSP, PC 게임 파일, 카드 이미지, 저장 데이터, 펌웨어와 키, 빌드 결과 ZIP은 각 PC에서 로컬 파일로 관리합니다. Git은 소스와 카드 정의를 동기화합니다.

## 스위치 파일 빌드

Python 3.12에서 저장소 루트의 PowerShell로 아래 명령을 실행합니다. 두 명령은 `Switch-Port`에 결과 ZIP을 만듭니다.

```powershell
python .\Switch-Port\Tools\build_speed_patch.py
python .\Switch-Port\Tools\build_card_data.py
```

2배속 ZIP에는 스위치 1.0.1의 빌드 ID를 대상으로 한 Atmosphère 패치가 들어 있습니다. 카드 데이터 ZIP에는 원본 카드와 새 카드의 ID 조회표, 이름과 설명, 속성, 이미지가 들어 있습니다. 실제 듀얼과 실기 동작은 게임 실행 테스트에서 확인합니다.
