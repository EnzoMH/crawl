from fastapi import FastAPI, Request, APIRouter, BackgroundTasks, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel
from typing import List, Dict

from dotenv import load_dotenv
from datetime import datetime, timedelta
import time
import os
import asyncio

# Selenium 관련
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# 예외 처리
from selenium.common.exceptions import (
    TimeoutException, 
    ElementClickInterceptedException
)

router = APIRouter()

# ─────────────────────────────────────────────────────────────────────────────
#    1. 환경설정 및 모델 정의
# ─────────────────────────────────────────────────────────────────────────────

class CrawlerRequest(BaseModel):
    """
    POST /bid/crawl 요청 바디에 쓰일 모델.
    - announcements_number: 사전규격등록번호
    - organization: 수요기관명
    """
    announcements_number: str
    organization: str

class ControlRequest(BaseModel):
    action: str

class CrawlingState:
    """
    크롤링 전체 상태를 관리하는 싱글톤 클래스.
    - is_running: 크롤링 진행 중 여부
    - active_connections: 현재 연결된 WebSocket 클라이언트 목록
    - last_crawl_time, next_crawl_time: 마지막 및 다음 크롤링 시간
    - collected_data: 크롤링 결과
    - forms_data: (선택적으로) 폼에서 받은 데이터
    """
    def __init__(self):
        self.is_running = False
        self.active_connections: List[WebSocket] = []
        self.crawler_task = None
        self.last_crawl_time = None
        self.next_crawl_time = None
        self.collected_data: List[Dict] = []
        self.forms_data: List[Dict] = []  # 폼 데이터 저장

    def schedule_next_run(self):
        """
        다음 크롤링 시간(next_crawl_time)을 1시간 뒤로 설정하고,
        마지막 크롤링 시각(last_crawl_time)을 현재로 갱신한다.
        """
        self.last_crawl_time = datetime.now()
        self.next_crawl_time = self.last_crawl_time + timedelta(hours=1)

    def get_remaining_time(self) -> Dict[str, int] | None:
        """
        다음 크롤링까지 남은 시간을 딕셔너리 형태로 반환.
        남은 시간이 0 이하이면 None을 반환한다.
        """
        if not self.next_crawl_time:
            return None

        now = datetime.now()
        remaining = self.next_crawl_time - now
        if remaining.total_seconds() <= 0:
            return None

        minutes = int(remaining.total_seconds() // 60)
        seconds = int(remaining.total_seconds() % 60)
        return {"minutes": minutes, "seconds": seconds}


class BidCrawlerConfig:
    """
    크롤링에 필요한 기본 환경설정.
    - slack_token: 슬랙 토큰 (dotenv에서 불러오기)
    - chrome_driver_path: ChromeDriver 경로
    - base_url: 크롤링할 사이트 기본 URL
    """
    def __init__(self):
        load_dotenv()
        self.slack_token = os.getenv('SLACK_BOT_TOKEN')  # 필요하면 사용
        self.chrome_driver_path = 'C:\\Users\\admin\\Downloads\\chromedriver-win64\\chromedriver.exe'
        self.base_url = 'https://www.g2b.go.kr'
        self.organization = None
        self.announcements_number = None
        
class WebDriverSetup:
    """
    셀레니움 WebDriver 세팅을 담당하는 클래스.
    - Chrome headless 또는 설정 옵션 지정 가능
    - 반환: (driver, wait)
    """
    @staticmethod
    def setup_driver():
        chrome_options = Options()
        chrome_options.add_argument('--headless=new')  # 필요 시 활성화
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--disable-extensions')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--memory-pressure-off')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--start-maximized')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        service = Service(BidCrawlerConfig().chrome_driver_path)
        driver = webdriver.Chrome(service=service, options=chrome_options)
        wait = WebDriverWait(driver, 10)  # 명시적 대기 10초
        
        # 혹은 driver.set_window_size(1920, 1080)
        return driver, wait


# ─────────────────────────────────────────────────────────────────────────────
#    2. 실제 크롤링 로직 클래스 정의
# ─────────────────────────────────────────────────────────────────────────────

class BidAnnouncementCrawler:
    """
    나라장터(g2b.go.kr)에서 입찰공고(사전규격등록번호)를 확인하는 크롤러.
    - initialize(): 사이트 접속 후 첫 팝업 처리
    - navigate_to_bid_list(): 입찰공고 목록으로 이동
    - handle_search_conditions(): 라디오버튼/상세조건 클릭 및 기관명 검색 등
    - search_announcements(): 공고 목록 검색 후 사전규격번호 매칭 확인
    - cleanup(): 드라이버 종료
    """
    def __init__(self):
        self.config = BidCrawlerConfig()
        self.driver, self.wait = WebDriverSetup.setup_driver()
        self.main_window = None  # 상세조건 팝업창 처리시 사용
        print(f"BidAnnouncementCrawler initialized with organization={self.config.organization} and announcements_number={self.config.announcements_number}")

    async def initialize(self):
        """사이트 접속 및 첫 팝업 닫기."""
        self.driver.get(self.config.base_url)
        print("입찰공고 추적 시작")
        await self.handle_initial_popup()

    async def handle_initial_popup(self):
        """
        첫 번째 팝업 처리.
        팝업 창이 뜨면 닫기 버튼을 찾아 클릭.
        """
        first_close_xpath = '//*[@id="mf_wfm_container_wq_uuid_877_wq_uuid_884_poupR23AB0000013415_close"]'
        close_button = self.wait.until(
            EC.element_to_be_clickable((By.XPATH, first_close_xpath))
        )
        close_button.click()
        print("첫 번째 팝업 닫기 성공")
        await asyncio.sleep(1)

    async def navigate_to_bid_list(self):
        """
        g2b 메인화면에서 입찰 → 입찰공고목록으로 이동.
        ID를 통해 해당 버튼들을 클릭.
        """
        try:
            # "입찰" 버튼 클릭
            ipchal_btn_id = "mf_wfm_gnb_wfm_gnbMenu_genDepth1_1_btn_menuLvl1_span"
            ipchal_btn = self.wait.until(EC.element_to_be_clickable((By.ID, ipchal_btn_id)))
            ipchal_btn.click()
            print("입찰 클릭 완료")
            time.sleep(2)
            
            # "입찰공고목록" 버튼 클릭
            ipchal_lists_id = 'mf_wfm_gnb_wfm_gnbMenu_genDepth1_1_genDepth2_0_genDepth3_0_btn_menuLvl3_span'
            ipchal_lists_btn = self.wait.until(EC.element_to_be_clickable((By.ID, ipchal_lists_id)))
            ipchal_lists_btn.click()
            print("입찰공고목록 클릭 완료")
            time.sleep(3)
        except Exception as e:
            print(f"입찰 목록 페이지 이동 실패: {str(e)}")

    async def handle_search_conditions(self):
        """
        검색 조건 설정:
        - 라디오 버튼 "입찰공고" 선택
        - 상세조건 버튼 클릭
        - 수요기관명 설정
        """
        try:
            await self.select_radio_button()
            await self.click_detail_condition()
            await self.set_organization_name()
        except Exception as e:
            print(f"검색 조건 설정 실패: {str(e)}")

    async def select_radio_button(self):
        """라디오 버튼 (입찰공고) 선택."""
        radio_button = self.wait.until(EC.element_to_be_clickable(
            (By.ID, "mf_wfm_container_tacBidPbancLst_contents_tab2_body_radSrchTy1_input_0")
        ))
        self.driver.execute_script("arguments[0].click();", radio_button)
        print("입찰공고 라디오 버튼 선택 완료")
        time.sleep(1)

    async def click_detail_condition(self):
        """
        '상세조건' 버튼 클릭.
        버튼 목록 중 현재 표시된 버튼을 찾아 클릭.
        """
        try:
            buttons = self.driver.find_elements(By.CSS_SELECTOR, "input[value='상세조건']")
            visible_button = next((btn for btn in buttons if btn.is_displayed()), None)
            
            if visible_button:
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", visible_button)
                time.sleep(1)
                visible_button.click()
                print("상세조건 클릭 완료")
                time.sleep(2)
                self.main_window = self.driver.current_window_handle
            else:
                raise Exception("표시된 상세조건 버튼을 찾을 수 없습니다")
        except Exception as e:
            print(f"상세조건 클릭 실패: {str(e)}")

    async def set_organization_name(self):
        """
        수요기관명 검색:
        - 수요기관명 체크박스
        - 돋보기 버튼
        - 기관명 입력 후 검색/선택
        """
        try:
            # 수요기관명 체크박스
            checkbox_xpath = '//*[@id="mf_wfm_container_tacBidPbancLst_contents_tab2_body_untyGrpGb1_input_1"]'
            org_checkbox = self.wait.until(EC.presence_of_element_located((By.XPATH, checkbox_xpath)))
            self.driver.execute_script("arguments[0].click();", org_checkbox)
            await asyncio.sleep(1)  # 클릭 후 잠시 대기
            
            # 돋보기 버튼
            magnifier_xpath = '//*[@id="mf_wfm_container_tacBidPbancLst_contents_tab2_body_btnDmstNmSrch1"]'
            magnifier_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, magnifier_xpath)))
            magnifier_btn.click()
            await asyncio.sleep(2)  # 팝업 창이 완전히 열릴 때까지 대기
            
            # 기관명 입력
            input_xpath = '//*[@id="mf_wfm_container_tacBidPbancLst_contents_tab2_body_FUUB008_01_wframe_popupCnts_ibxSrchDmstNm"]'
            input_field = self.wait.until(EC.presence_of_element_located((By.XPATH, input_xpath)))
            input_field.clear()  # 기존 입력값 제거
            input_field.send_keys(self.config.organization)
            await asyncio.sleep(1)
            
            # 검색 버튼 클릭
            search_btn_xpath = '//*[@id="mf_wfm_container_tacBidPbancLst_contents_tab2_body_FUUB008_01_wframe_popupCnts_btnS0001"]'
            search_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, search_btn_xpath)))
            search_btn.click()
            await asyncio.sleep(2)  # 검색 결과가 로드될 때까지 대기
            
            # 검색 결과 확인 및 선택
            try:
                result_xpath = '//*[@id="mf_wfm_container_tacBidPbancLst_contents_tab2_body_FUUB008_01_wframe_popupCnts_grdDmstSrch_cell_0_2"]/nobr/a'
                result = self.wait.until(EC.presence_of_element_located((By.XPATH, result_xpath)))
                result.click()
                await asyncio.sleep(1)
                
                # 최종 검색 버튼 클릭
                final_search_xpath = '//*[@id="mf_wfm_container_tacBidPbancLst_contents_tab2_body_btnS0004"]'
                final_search_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, final_search_xpath)))
                final_search_btn.click()
                await asyncio.sleep(2)
                
                print("수요기관명 설정 완료")
                
            except TimeoutException:
                print("검색 결과가 없습니다.")
                raise Exception(f"'{self.config.organization}' 기관에 대한 검색 결과를 찾을 수 없습니다.")
                
        except Exception as e:
            print(f"수요기관명 설정 실패: {str(e)}")
            raise

    async def select_organization(self):
        """
        기관 검색 결과에서 첫 번째 항목을 선택하고, 최종 검색 버튼 클릭.
        """
        try:
            # 검색 버튼
            search_btn_xpath = '//*[@id="mf_wfm_container_tacBidPbancLst_contents_tab2_body_FUUB008_01_wframe_popupCnts_btnS0001"]'
            search_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, search_btn_xpath)))
            search_btn.click()
            
            # 검색 결과 선택
            result_xpath = '//*[@id="mf_wfm_container_tacBidPbancLst_contents_tab2_body_FUUB008_01_wframe_popupCnts_grdDmstSrch_cell_0_2"]/nobr/a'
            result = self.wait.until(EC.element_to_be_clickable((By.XPATH, result_xpath)))
            result.click()
            
            # 최종 검색
            final_search_xpath = '//*[@id="mf_wfm_container_tacBidPbancLst_contents_tab2_body_btnS0004"]'
            final_search_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, final_search_xpath)))
            final_search_btn.click()
        except Exception as e:
            print(f"기관 선택 실패: {str(e)}")

    def check_announcement(self, row_index: int) -> bool:
        """
        주어진 인덱스의 공고를 열어 사전규격등록번호가 일치하는지 확인.
        일치하면 True, 아니면 False 반환.
        """
        try:
            # 공고 링크 클릭
            ann_xpath = f'//*[@id="mf_wfm_container_tacBidPbancLst_contents_tab2_body_gridView1_cell_{row_index}_6"]/nobr/a'
            ann_elem = self.wait.until(EC.element_to_be_clickable((By.XPATH, ann_xpath)))
            ann_elem.click()
            time.sleep(2)
            
            # 사전규격번호 확인
            return self.verify_specification_number(row_index)
        except Exception as e:
            print(f"⚠️ {row_index+1}번째 공고 확인 중 오류 발생: {str(e)}")
            return False
        finally:
            # 상세페이지 닫고 목록으로 복귀
            self.driver.back()
            time.sleep(1)

    def verify_specification_number(self, row_index: int) -> bool:
        """
        상세 페이지에서 사전규격번호를 추출하여
        self.config.announcements_number와 일치하는지 비교.
        """
        try:
            # 페이지 맨 아래로 스크롤
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            
            spec_number_elem = self.wait.until(EC.presence_of_element_located(
                (By.XPATH, '//*[@id="mf_wfm_container_mainWframe_ancBfSpec"]')
            ))
            
            # 사전규격번호가 표시되지 않거나 비어있으면 False
            if not spec_number_elem.is_displayed() or not spec_number_elem.text.strip():
                print(f"💡 {row_index+1}번째 공고: 사전규격등록번호가 없습니다.")
                return False
            
            # 텍스트 비교
            spec_number_text = spec_number_elem.text.strip()
            if spec_number_text == str(self.config.announcements_number):
                print(f"✅ {row_index+1}번째 공고: 사전규격 {spec_number_text} 일치.")
                return True
            else:
                print(f"❌ {row_index+1}번째 공고: 일치하지 않습니다. (찾은 번호: {spec_number_text})")
                return False
        except Exception as e:
            print(f"💡 {row_index+1}번째 공고: 사전규격등록번호가 없습니다.")
            return False

    async def search_announcements(self, max_rows: int = 10) -> bool:
        """
        공고 목록에서 최대 max_rows 개를 확인하며
        사전규격번호가 일치하는 공고를 찾으면 True, 끝까지 못 찾으면 False 반환.
        """
        found = False
        for i in range(max_rows):
            if self.check_announcement(i):
                found = True
                print(f"\n✨ {i+1}번째 공고가 일치합니다.")
                break
        if not found:
            print("\n❌ 일치하는 공고를 찾지 못했습니다.")
        return found

    async def cleanup(self):
        """
        크롤러 종료 시 Driver 닫기.
        """
        if self.driver:
            self.driver.quit()


# ─────────────────────────────────────────────────────────────────────────────
#    3. 글로벌 상태 및 유틸 함수
# ─────────────────────────────────────────────────────────────────────────────

crawling_state = CrawlingState()

async def broadcast_status():
    """
    현재 크롤링 상태를 연결된 WebSocket 모두에게 브로드캐스트.
    - is_running
    - remaining_time
    - forms_data
    """
    if not crawling_state.active_connections:
        return
    
    message = {
        "type": "status",
        "data": {
            "is_running": crawling_state.is_running,
            "remaining_time": crawling_state.get_remaining_time(),
            "forms_data": crawling_state.forms_data
        }
    }
    
    for connection in crawling_state.active_connections:
        try:
            await connection.send_json(message)
        except:
            pass


# ─────────────────────────────────────────────────────────────────────────────
#    4. 라우터 엔드포인트 정의
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/bid/crawl")
async def crawl_bid(request: CrawlerRequest):
    """
    단일 POST 요청으로 특정 '사전규격등록번호'와 '수요기관명'을 기준으로
    1회 크롤링을 실행하는 엔드포인트.
    """
    crawler = BidAnnouncementCrawler()
    try:
        crawler.config.announcements_number = request.announcements_number
        crawler.config.organization = request.organization
        
        await crawler.initialize()
        await crawler.navigate_to_bid_list()
        await crawler.handle_search_conditions()
        found = await crawler.search_announcements()
        
        return {"success": True, "found": found}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await crawler.cleanup()


@router.post("/bid/control")
async def control_crawling(req: ControlRequest):
    if req.action == "start":
        if not crawling_state.is_running:
            crawling_state.is_running = True
            crawling_state.schedule_next_run()
            
            # 실제 크롤링 로직을 여기서 바로 호출
            crawler = BidAnnouncementCrawler()
            try:
                await crawler.initialize()
                await crawler.navigate_to_bid_list()
                await crawler.handle_search_conditions()
                found = await crawler.search_announcements()
                print(f"크롤링 결과: found={found}")
            except Exception as e:
                print(f"오류: {e}")
            finally:
                await crawler.cleanup()
            
            return {"status": "started", "message": "크롤링이 실행되었습니다."}


@router.get("/bid/status")
async def get_crawling_status():
    """
    현재 크롤링 상태 조회용 GET 엔드포인트.
    - is_running
    - remaining_time
    - forms_data
    """
    remaining_time = crawling_state.get_remaining_time()
    return {
        "is_running": crawling_state.is_running,
        "remaining_time": remaining_time,
        "forms_data": crawling_state.forms_data
    }


# ─────────────────────────────────────────────────────────────────────────────
#    5. WebSocket 연결
# ─────────────────────────────────────────────────────────────────────────────

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket 연결 엔드포인트.
    - 연결 시 현재 상태 전송
    - 텍스트 수신 대기
    - 연결 종료 시 리스트에서 제거
    """
    await websocket.accept()
    crawling_state.active_connections.append(websocket)

    try:
        # 연결되면 초기에 상태 전송
        await websocket.send_json({
            "type": "status",
            "data": {
                "is_running": crawling_state.is_running,
                "remaining_time": crawling_state.get_remaining_time(),
                "forms_data": crawling_state.forms_data
            }
        })

        # 메시지 대기 루프
        while True:
            await websocket.receive_text()  # 텍스트 수신
    except WebSocketDisconnect:
        crawling_state.active_connections.remove(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
        if websocket in crawling_state.active_connections:
            crawling_state.active_connections.remove(websocket)


# ─────────────────────────────────────────────────────────────────────────────
#    6. 메인 실행부
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    """
    파일 단독 실행 시 테스트용 main 함수를 실행.
    한 번의 크롤링 프로세스를 실행하기 위한 예시.
    """
    crawler = BidAnnouncementCrawler()
    try:
        await crawler.initialize()
        await crawler.navigate_to_bid_list()
        await crawler.handle_search_conditions()
        await crawler.search_announcements()
    finally:
        await crawler.cleanup()


if __name__ == "__main__":
    # python filename.py 로 실행하면 main()을 돌림
    asyncio.run(main())