# 유희왕 Link Evolution 개발

스위치 1.0.1용 2배속 패치와 카드 이식 도구, Windows판 덱 선택 수정 소스, PC 카드 모드의 정의와 설정을 담습니다. 추가 카드 데이터는 스위치판의 카드 등록·저장·효과 코드 작업을 거쳐야 실제 듀얼에서 쓸 수 있습니다.

## 다른 PC에서 이어서 작업하기

1. Git for Windows가 설치된 PC에서 `git clone https://github.com/yjmjeminq/YGO-PC-Full.git`으로 저장소를 복제합니다.
2. 복제한 폴더에서 `Setup-YGO.cmd`를 실행하고 환경 복구 키 파일의 한 줄을 입력합니다. 환경 다운로드에는 GitHub 로그인이 필요 없습니다.
3. 설치가 끝나면 Windows판 파일과 카드 이미지, 스위치용 빌드 입력 및 결과가 복제한 폴더에 준비됩니다. 폴더 안의 Ryujinx는 펌웨어 15.0.0, 1.0.1 업데이트, 2배속 패치를 사용합니다.

환경 묶음은 공개 릴리스에서 암호화된 상태로 내려받고 복구 키로 해제합니다. 다운로드와 설치 중 약 21GiB의 여유 공간이 필요합니다. 설치를 다시 실행해도 기존 게임 파일과 세이브는 보존합니다. [환경 릴리스](https://github.com/yjmjeminq/YGO-PC-Full-Environment/releases/tag/windows-v1)

평소에는 작업 시작 전에 `git pull --ff-only`를 실행하고, 수정한 소스와 카드 정의를 커밋한 뒤 `git push` 합니다. 환경 릴리스에는 만들 당시의 게임 파일, 카드 이미지, 세이브, 빌드 결과가 들어 있습니다.

## 스위치 파일 빌드

Python 3.12에서 저장소 루트의 PowerShell로 아래 명령을 실행합니다. 두 명령은 `Switch-Port`에 결과 ZIP을 만듭니다.

```powershell
python .\Switch-Port\Tools\build_speed_patch.py
python .\Switch-Port\Tools\build_card_data.py
```

2배속 ZIP에는 스위치 1.0.1의 빌드 ID를 대상으로 한 Atmosphère 패치가 들어 있습니다. 카드 데이터 ZIP에는 원본 카드와 새 카드의 ID 조회표, 이름과 설명, 속성, 이미지가 들어 있습니다. 실제 듀얼과 실기 동작은 게임 실행 테스트에서 확인합니다.
