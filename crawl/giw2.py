from fastapi import FastAPI, WebSocket, APIRouter, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse
from pydantic import BaseModel
from typing import List, Dict
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from threading import Timer
from datetime import datetime, timedelta


import asyncio, json, gc, uvicorn, webbrowser, os

app = FastAPI(title="사전규격공개 + 입찰공고 크롤링 API")
router = APIRouter()
# CORS 미들웨어 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=["*"],
)


# 정적 파일 서빙 (assets 디렉토리를 '/assets' 경로에 매핑)
app.mount("/assets", StaticFiles(directory="static/assets"), name="assets")

SLACK_TOKEN = "xoxb-7772790073142-7779533740258-faMs1MjHOqHhCQM92NIci5d3"
slack_client = WebClient(token=SLACK_TOKEN)

# 크롤링할 검색어 리스트
SEARCH_TERMS = [
    "LED경관조명기구",
    "경관조명기구",
    "교육용로봇",
    "동영상제작서비스",
    "디자인서비스",
    "안내전광판",
    "영상정보디스플레이장치",
    "조명용제어장치",
    "조형물",
    "실물모형및전시물",
]

class CrawlingState:
    def __init__(self):
        self.is_running = False                     # 크롤링 실행 여부
        self.current_term = ""                      # 현재 진행 중인 검색어
        self.active_connections: List[WebSocket] = []  # 활성 WebSocket 목록
        self.crawler_task = None
        self.last_crawl_time = None
        self.next_crawl_time = None

        self.collected_data: List[Dict] = []        # 크롤링으로 모은 데이터
        self.scheduler_task = None                  # 크롤링을 주기적으로 실행하는 태스크
        self.completed_terms: List[str] = []        # 이미 완료된 검색어 목록
        self.current_term_index = 0                 # 현재 진행 중인 검색어 인덱스
        
    def save_progress(self):
        if self.current_term in SEARCH_TERMS:
            current_index = SEARCH_TERMS.index(self.current_term)
            self.completed_terms = SEARCH_TERMS[:current_index]
            self.current_term_index = current_index
        
    def restore_progress(self):
        if self.completed_terms:
            self.current_term_index = len(self.completed_terms)
            return True
        return False

crawling_state = CrawlingState() # 전역 상태 인스턴스

def cleanup_resources(driver=None):
    if driver:
        driver.quit()
    gc.collect()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    crawling_state.active_connections.append(websocket)
    try:
        while True:
            await websocket.receive_text()
            if not crawling_state.is_running:
                break
            # 현재까지 수집된 데이터 전송
            await websocket.send_json({
                "type": "data",
                "data": crawling_state.collected_data
            })
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        crawling_state.active_connections.remove(websocket)


async def broadcast_message(message: dict):
    for connection in crawling_state.active_connections:
        try:
            await connection.send_json(message)
        except:
            crawling_state.active_connections.remove(connection)

@app.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    crawling_state.active_connections.append(websocket)

    try:
        await websocket.send_json({
            "type": "status",
            "data": {
                "is_running": crawling_state.is_running,
                "remaining_time": crawling_state.get_remaining_time(),
                "forms_data": crawling_state.forms_data
            }
        })
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        crawling_state.active_connections.remove(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
        if websocket in crawling_state.active_connections:
            crawling_state.active_connections.remove(websocket)

class WebDriver:
    def __init__(self):
        self.driver = None
        self.wait = None
    
    def setup(self):
        chrome_options = Options()
        chrome_options.add_argument('--headless=new')
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
        
        service = Service('C:\\Users\\admin\\Downloads\\chromedriver-win64\\chromedriver.exe')
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        self.wait = WebDriverWait(self.driver, 10)

        self.driver.set_window_size(1920, 1080)
        return self.driver, self.wait

# class PopupHandler:
#     @staticmethod
#     async def handle_popups(driver, wait):
#         if not crawling_state.is_running:
#             return
#         first_close_css = "div.w2window_close[title='창닫기']"
#         first_close_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, first_close_css)))
#         first_close_button.click()
#         print("첫 번째 팝업 닫기 성공")
            
#         if not crawling_state.is_running:
#             return
#         await asyncio.sleep(2)

class NavigationHandler:
    def __init__(self, driver, wait):
        self.driver = driver
        self.wait = wait
        self.main_window = None
    
    async def navigate_to_pre_spec(self):
        if not crawling_state.is_running:
            return
            
        try:
            balju = self.wait.until(EC.element_to_be_clickable(
                (By.ID, "mf_wfm_gnb_wfm_gnbMenu_genDepth1_0_btn_menuLvl1_span"))
            )
            balju.click()
            
            if not crawling_state.is_running:
                return
            await asyncio.sleep(2)
            
            balju_list = self.wait.until(EC.element_to_be_clickable(
                (By.ID, "mf_wfm_gnb_wfm_gnbMenu_genDepth1_0_genDepth2_0_btn_menuLvl2_span"))
            )
            balju_list.click()
            
            if not crawling_state.is_running:
                return
            await asyncio.sleep(2)
            
            pre_spec = self.wait.until(EC.element_to_be_clickable(
                (By.ID, "mf_wfm_container_radSrchTy_input_1"))
            )
            self.driver.execute_script("arguments[0].click();", pre_spec)
            
            if not crawling_state.is_running:
                return
            await asyncio.sleep(2)
            
        except Exception as e:
            print(f"네비게이션 중 오류: {e}")
            raise e

class SearchHandler:
    def __init__(self, driver, wait):
        self.driver = driver
        self.wait = wait
        self.main_window = None
    
    async def search_product(self, search_term):
        if not crawling_state.is_running:
            return
            
        try:
            # 상세조건 클릭
            detail_condition = self.wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "input.w2trigger.btn_cm.srch_toggle[value='상세조건']"))
            )
            self.driver.execute_script("arguments[0].click();", detail_condition)
            
            if not crawling_state.is_running:
                return
            await asyncio.sleep(2)
            
            # '물품' 체크박스
            products = self.wait.until(EC.element_to_be_clickable(
                (By.ID, 'mf_wfm_container_chkRqdcBsneSeCd_input_1'))
            )
            self.driver.execute_script("arguments[0].click();", products)
            
            if not crawling_state.is_running:
                return
            await asyncio.sleep(2)
            
            self.main_window = self.driver.current_window_handle
            
            # '세부품명' 검색(돋보기)
            magnifier = self.wait.until(EC.element_to_be_clickable(
                (By.ID, 'mf_wfm_container_btnPrnmNoPoup2'))
            )
            self.driver.execute_script("arguments[0].click();", magnifier)
            
            if not crawling_state.is_running:
                return
            await asyncio.sleep(2)
            
            # 검색어 입력
            spec_products = self.wait.until(EC.element_to_be_clickable(
                (By.ID, 'mf_wfm_container_DtlsPrnmSrchPL_wframe_popupCnts_ibxDtlsPrnm'))
            )
            spec_products.click()
            spec_products.send_keys(search_term)
            
            if not crawling_state.is_running:
                return
            await asyncio.sleep(2)
            
            # 검색 버튼 클릭
            spec_magnifier = self.wait.until(EC.element_to_be_clickable(
                (By.ID, 'mf_wfm_container_DtlsPrnmSrchPL_wframe_popupCnts_btnS0001'))
            )
            spec_magnifier.click()
            
            if not crawling_state.is_running:
                return
            await asyncio.sleep(2)
            
            await self.handle_search_results(search_term)
            
        except Exception as e:
            print(f"검색 중 오류: {e}")
            raise e

    async def handle_search_results(self, search_term):
        if not crawling_state.is_running:
            return
            
        try:
            cells_base_xpath = (
                '//*[contains(@id, "mf_wfm_container_DtlsPrnmSrchPL_wframe_popupCnts_grdDtlsPrnm_cell_") '
                'and contains(@id, "_1")]'
            )
            cells = self.driver.find_elements(By.XPATH, cells_base_xpath)
            
            matching_cell = None
            for cell in cells:
                if cell.text == search_term:
                    matching_cell = cell
                    print(f"정확히 일치하는 항목 '{search_term}' 찾음")
                    break
            
            if matching_cell:
                actions = ActionChains(self.driver)
                actions.double_click(matching_cell).perform()
                
                if not crawling_state.is_running:
                    return
                await asyncio.sleep(2)
            else:
                raise Exception(f"검색어 '{search_term}'와 일치하는 세부품명이 없습니다.")
            
            await self.handle_windows()
            await self.perform_final_search()
            
        except Exception as e:
            print(f"검색 결과 처리 중 오류: {e}")
            raise e

    async def handle_windows(self):
        if not crawling_state.is_running:
            return
            
        try:
            all_windows = self.driver.window_handles
            for window in all_windows:
                if window != self.main_window:
                    self.driver.switch_to.window(window)
                    
                    if not crawling_state.is_running:
                        return
                    await asyncio.sleep(2)
                    
                    self.driver.close()
            
            self.driver.switch_to.window(self.main_window)
            
        except Exception as e:
            print(f"윈도우 처리 중 오류: {e}")
            raise e

    async def perform_final_search(self):
        if not crawling_state.is_running:
            return
            
        try:
            final_magnifier = self.wait.until(EC.element_to_be_clickable(
                (By.ID, 'mf_wfm_container_btnS0001'))
            )
            final_magnifier.click()
            
            if not crawling_state.is_running:
                return
            await asyncio.sleep(2)
            
        except Exception as e:
            print(f"최종 검색 중 오류: {e}")
            raise e

class DataExtractor:
    def __init__(self, driver, wait, search_term):
        self.driver = driver
        self.wait = wait
        self.search_term = search_term
        self.slack_client = slack_client

    async def extract_detail_info(self):
        if not crawling_state.is_running:
            return None
        try:
            fields = {
                "사전규격등록번호": "//input[@class='w2input df_input w2input_readonly' and @title='사전규격등록번호']",
                "사전규격명": "//label[@class='w2textbox ' and @style='width:calc(100%)']",
                "수요기관": "//input[@class='w2input df_input w2input_readonly' and @title='수요기관']",
                "배정예산액": "//input[@class='w2input df_input tar w2input_readonly' and @title='배정예산액']",
                "의견등록마감일시": "//input[@class='w2input df_input w2input_readonly' and @style='width:200px;']",
                "사전규격공개일시": "//input[@id='mf_wfm_container_alotBgtPrspAmt']"
            }
            detail_info = {"search_term": self.search_term}
            
            for field_name, xpath in fields.items(): # 각 필드 하나씩 찾아서 값 추출
                if not crawling_state.is_running:
                    return None
                try:
                    element = self.wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
                    value = element.get_attribute("value") if field_name != "사전규격명" else element.text # 사전규격명은 .text, 나머지는 value
                    print(f"필드 {field_name}: {value}")
                    detail_info[field_name] = value
                except Exception as e:
                    print(f"{field_name} 필드 추출 중 오류: {e}")
                    detail_info[field_name] = None
            
            # 사전규격공개일시가 오늘이면 Slack 알림
            if detail_info.get('사전규격공개일시'):
                today = datetime.now().strftime('%Y%m%d')
                notice_date = detail_info['사전규격공개일시'].split()[0]
                
                if notice_date == today:
                    await self.send_slack_notification(detail_info)
            
            return detail_info
                
        except Exception as e:
            print(f"상세 정보 추출 중 오류: {e}")
            return None

    async def send_slack_notification(self, detail_info):
        try:
            slack_message = (
                f"🔔 새로운 사전규격 공고 🔔\n\n"
                f"사전규격명: {detail_info['사전규격명']}\n"
                f"사전규격등록번호: {detail_info['사전규격등록번호']}\n"
                f"수요기관: {detail_info['수요기관']}\n"
                f"배정예산액: {detail_info['배정예산액']}원\n"
                f"의견등록마감일시: {detail_info['의견등록마감일시']}\n"
            )
            
            response = self.slack_client.chat_postMessage(
                channel="C07NR1N7NNA",
                text=slack_message
            )
            
            if response['ok']:
                print(f"Slack 알림 전송 완료: {detail_info['사전규격등록번호']}")
            else:
                print(f"Slack 알림 전송 실패: {response['error']}")
        except Exception as e:
            print(f"Slack 알림 전송 중 오류 발생: {e}")

    async def extract_all_items(self):
        if not crawling_state.is_running:
            return []
            
        collected_results = []
        try:
            # 목록 중 사전규격명을 클릭하는 부분(_11)
            cells_xpath = "//td[contains(@id, 'mf_wfm_container_gridView1_cell_') and contains(@id, '_11')]/nobr/a"
            cells = self.driver.find_elements(By.XPATH, cells_xpath)
            
            # 표시되고, 텍스트가 있는 셀만 카운트
            total_items = len([cell for cell in cells if cell.is_displayed() and cell.text.strip()])
            
            if total_items == 0:
                return collected_results
            
            # 각 아이템을 하나씩 열어 상세 정보 추출
            for i in range(total_items):
                if not crawling_state.is_running:
                    return collected_results
                    
                try:
                    current_xpath = f'//*[@id="mf_wfm_container_gridView1_cell_{i}_11"]/nobr/a'
                    if self.driver.find_element(By.XPATH, current_xpath).is_displayed():
                        link_elem = self.wait.until(EC.element_to_be_clickable((By.XPATH, current_xpath)))
                        self.driver.execute_script("arguments[0].click();", link_elem)
                        
                        if not crawling_state.is_running:
                            return collected_results
                        await asyncio.sleep(2)
                        
                        # 상세 추출
                        result = await self.extract_detail_info()
                        if result:
                            collected_results.append(result)

                        # 다시 목록으로
                        self.driver.back()
                        
                        if not crawling_state.is_running:
                            return collected_results
                        await asyncio.sleep(2)
                        
                except Exception as e:
                    print(f"{i+1}번째 항목 처리 중 오류: {e}")
                    continue
                    
        except Exception as e:
            print(f"데이터 추출 중 오류 발생: {e}")
        
        return collected_results

async def perform_crawling():
    try:
        if not crawling_state.is_running:
            return

        # 마지막/다음 크롤링 시간 기록
        crawling_state.last_crawl_time = datetime.now()
        crawling_state.next_crawl_time = crawling_state.last_crawl_time + timedelta(hours=1)
        
        # 이전 진행 상태 복원 후, 남은 검색어만 순회
        start_index = crawling_state.current_term_index
        search_terms = SEARCH_TERMS[start_index:]
        
        for search_term in search_terms:
            if not crawling_state.is_running:
                crawling_state.save_progress()
                break
                
            # 새로운 드라이버 세팅
            web_driver = WebDriver()
            driver, wait = web_driver.setup()
            
            try:
                crawling_state.current_term = search_term
                # 진행률 계산
                current_progress = ((start_index + search_terms.index(search_term) + 1) / len(SEARCH_TERMS)) * 100
                
                # 현재 검색어, 진행률 등 WebSocket으로 브로드캐스트
                await broadcast_message({
                    "type": "status",
                    "data": f"{search_term} 크롤링 중... (진행률: {current_progress:.1f}%)"
                })
                
                # 사이트 접속
                driver.get('https://www.g2b.go.kr')
                
                if not crawling_state.is_running:
                    crawling_state.save_progress()
                    break
                await asyncio.sleep(2)
                
                # # 팝업 처리
                # popup_handler = PopupHandler()
                # await popup_handler.handle_popups(driver, wait)
                
                # if not crawling_state.is_running:
                #     crawling_state.save_progress()
                #     break
                
                # 페이지 이동
                navigation = NavigationHandler(driver, wait)
                await navigation.navigate_to_pre_spec()
                
                if not crawling_state.is_running:
                    crawling_state.save_progress()
                    break
                
                # 상세 검색
                search_handler = SearchHandler(driver, wait)
                await search_handler.search_product(search_term)
                
                if not crawling_state.is_running:
                    crawling_state.save_progress()
                    break
                
                # 데이터 추출
                data_extractor = DataExtractor(driver, wait, search_term)
                results = await data_extractor.extract_all_items()
                
                if results:
                    crawling_state.collected_data.extend(results)
                    await broadcast_message({
                        "type": "data",
                        "data": results
                    })
                
                # 검색어 완료 처리
                if search_term not in crawling_state.completed_terms:
                    crawling_state.completed_terms.append(search_term)
                crawling_state.current_term_index = SEARCH_TERMS.index(search_term) + 1
                
                if not crawling_state.is_running:
                    crawling_state.save_progress()
                    break
                await asyncio.sleep(2)
                
            except Exception as e:
                print(f"{search_term} 처리 중 오류 발생: {e}")
                crawling_state.save_progress()
                await broadcast_message({
                    "type": "error",
                    "data": f"{search_term} 처리 중 오류: {str(e)}"
                })
                
            finally:
                cleanup_resources(driver)
        
        # 모든 검색어를 처리한 경우 상태 초기화
        if crawling_state.current_term_index >= len(SEARCH_TERMS):
            crawling_state.current_term_index = 0
            crawling_state.completed_terms = []
                    
        await broadcast_message({
            "type": "complete",
            "data": {
                "message": "크롤링이 완료되었습니다.",
                "lastCrawlTime": crawling_state.last_crawl_time.strftime("%Y-%m-%d %H:%M:%S"),
                "nextCrawlTime": crawling_state.next_crawl_time.strftime("%Y-%m-%d %H:%M:%S"),
                "completedTerms": crawling_state.completed_terms,
                "progress": f"{(len(crawling_state.completed_terms) / len(SEARCH_TERMS)) * 100:.1f}%"
            }
        })
            
    except Exception as e:
        print(f"Perform crawling error: {e}")
        crawling_state.save_progress()
        await broadcast_message({
            "type": "error",
            "data": str(e)
        })

async def scheduled_crawling():
    while True:
        try:
            if not crawling_state.is_running:
                break
            await perform_crawling()
            for _ in range(360): # 정확히 1시간 대기 (10초씩 360번)
                if not crawling_state.is_running:
                    break
                await asyncio.sleep(10)
                
        except asyncio.CancelledError: # 태스크가 취소되면 루프 종료
            break
        except Exception as e:
            print(f"Scheduled crawling error: {e}")
            if crawling_state.is_running:
                await asyncio.sleep(60)  # 에러 발생 시 1분 후 재시도

@app.get("/{full_path:path}")
async def serve_app(full_path: str):
    return FileResponse("static/index.html")

@app.post("/api/start")
async def start_crawling():
    if not crawling_state.is_running:
        crawling_state.is_running = True
        if crawling_state.scheduler_task is None:
            crawling_state.scheduler_task = asyncio.create_task(scheduled_crawling())
        return {"message": "크롤링이 시작되었습니다."}
    return {"message": "크롤링이 이미 실행 중입니다."}


@app.post("/api/stop")
async def stop_crawling():
    if crawling_state.is_running:
        crawling_state.is_running = False
        crawling_state.save_progress()
        if crawling_state.scheduler_task:
            crawling_state.scheduler_task.cancel()
            crawling_state.scheduler_task = None
        return {
            "message": "크롤링이 중지되었습니다.",
            "progress": {
                "completed_terms": crawling_state.completed_terms,
                "current_term": crawling_state.current_term
            }
        }
    return {"message": "크롤링이 실행 중이 아닙니다."}


@app.get("/api/status")
async def get_status():
    return {
        "is_running": crawling_state.is_running,
        "current_term": crawling_state.current_term,
        "collected_data": crawling_state.collected_data,
        "last_crawl_time": (crawling_state.last_crawl_time.strftime("%Y-%m-%d %H:%M:%S")
                            if crawling_state.last_crawl_time else None),
        "next_crawl_time": (crawling_state.next_crawl_time.strftime("%Y-%m-%d %H:%M:%S")
                            if crawling_state.next_crawl_time else None),
        "completed_terms": crawling_state.completed_terms,
        "progress_percentage": (
            (len(crawling_state.completed_terms) / len(SEARCH_TERMS)) * 100
            if crawling_state.completed_terms else 0
        )
    }

@app.get("/api/results")
async def get_results():
    return {"results": crawling_state.collected_data}

def open_browser():
    webbrowser.open("http://192.168.132.216:8000")

if __name__ == "__main__":
    Timer(1.5, open_browser).start() # 1.5초 후 브라우저 자동 오픈
    uvicorn.run("pre_spec:app", host="0.0.0.0", port=8000)