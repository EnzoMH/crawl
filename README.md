제공해주신 디렉토리 구조와 코드를 바탕으로 README.md를 작성해 드리겠습니다. main.py와 crawler_core.py를 중심으로 설명하겠습니다.

```markdown
# 입찰 공고 크롤링 서버

## 프로젝트 소개
이 프로젝트는 나라장터(G2B) 입찰 공고를 자동으로 크롤링하여 데이터를 수집, 처리하는 웹 서버입니다. FastAPI 프레임워크를 기반으로 구축되어 있으며, Selenium을 활용한 웹 크롤링 기능을 제공합니다.

## 주요 기능
- 키워드 기반 입찰 공고 자동 크롤링
- 실시간 크롤링 진행 상황 모니터링 (WebSocket 활용)
- 크롤링 결과 JSON 및 Excel 형식 저장
- 웹 기반 사용자 인터페이스
- API 기반 크롤링 검색 및 결과 조회

## 기술 스택
- **백엔드**: FastAPI, Python 3.11
- **크롤링**: Selenium, Chrome WebDriver
- **프론트엔드**: HTML, CSS, JavaScript
- **데이터 처리**: Pandas
- **비동기 처리**: asyncio

## 설치 방법

### 필수 요구사항
- Python 3.11 이상
- Chrome 브라우저 및 해당 버전의 ChromeDriver
- Git

### 설치 과정
1. 저장소 클론
   ```bash
   git clone https://github.com/your-username/crawl-main.git
   cd crawl-main
   ```

2. 가상 환경 설정 및 패키지 설치
   ```bash
   python -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. 환경 변수 설정
   `.env` 파일을 프로젝트 루트에 생성하고 다음 정보를 입력:
   ```
   G2B_ID=your_g2b_id
   G2B_PW=your_g2b_password
   ```

## 실행 방법
```bash
cd crawl
python main.py
```
서버가 실행되면 `http://localhost:8000`으로 접속하여 웹 인터페이스를 사용할 수 있습니다.

## API 엔드포인트

### 기본 엔드포인트
- `GET /` - 웹 인터페이스 홈페이지

### API 엔드포인트
- `POST /api/search` - 키워드 기반 입찰 공고 검색
- `POST /api/start` - 일괄 크롤링 시작
- `POST /api/stop` - 진행 중인 크롤링 중지
- `GET /api/crawl-results/` - 최신 크롤링 결과 조회
- `GET /api/download-excel/{filename}` - 엑셀 파일 다운로드

### WebSocket 엔드포인트
- `WebSocket /ws` - 실시간 크롤링 진행 상황 모니터링

## 사용 예시

### 웹 인터페이스 사용
1. 브라우저에서 `http://localhost:8000` 접속
2. 검색 키워드와 날짜 범위 입력
3. 검색 버튼 클릭
4. 실시간으로 크롤링 진행 상황 확인
5. 결과 확인 및 필요시 엑셀 다운로드

### API 사용 예시
```python
import requests
import json

# 키워드 검색 예시
search_data = {
    "keywords": ["VR", "AR"],
    "startDate": "2025-01-03",
    "endDate": "2025-02-03"
}

response = requests.post(
    "http://localhost:8000/api/search", 
    json=search_data
)
results = response.json()
print(f"검색 결과: {len(results['results'])}건")
```

## 프로젝트 구조
```
crawl/
├── data/                      # 크롤링 결과 저장 폴더
├── main.py                    # 메인 애플리케이션 (FastAPI)
├── test.py                    # 크롤링 테스트 파일
├── utils/                     # 유틸리티 모듈
│   ├── crawler_core.py        # 크롤링 핵심 로직
│   ├── constants.py           # 검색 키워드 등 상수
│   ├── error_handler.py       # 에러 처리
│   └── http_client.py         # HTTP 클라이언트
├── data_processor.py          # 데이터 처리 및 Excel 생성
└── static/                    # 정적 파일
    ├── home.html              # 메인 페이지
    ├── css/                   # CSS 파일
    └── js/                    # JavaScript 파일
        └── main.js            # 프론트엔드 로직
```

## 주요 파일 설명

### main.py
FastAPI 웹 서버의 메인 파일로, API 엔드포인트와 WebSocket 기능을 제공합니다.

### utils/crawler_core.py
Selenium 기반 크롤링 로직을 구현한 핵심 파일입니다. 나라장터 웹사이트 접속, 로그인, 검색, 데이터 추출 등의 기능을 제공합니다.

### static/home.html & static/js/main.js
사용자 인터페이스와 프론트엔드 로직을 담당하는 파일들입니다.

## 주의사항
- 크롤링은 대상 웹사이트의 이용약관을 준수하여 사용해야 합니다.
- 과도한 요청은 대상 서버에 부하를 줄 수 있으므로 적절한 간격을 두고 사용하세요.
- 크롤링한 데이터의 이용은 관련 법규를 준수해야 합니다.
```

이 README.md는 기본적인 구조와 정보를 담고 있습니다. 추가로 필요한 정보가 있으면 더 보완해 드릴 수 있습니다. 프로젝트의 구체적인 목적이나 사용 방법에 대한 추가 정보가 있으면 알려주세요.
