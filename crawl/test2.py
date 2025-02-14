import asyncio
import logging
from datetime import datetime, timedelta
import json
import requests
from typing import Dict, List, Optional
from dotenv import load_dotenv
import os

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'crawler_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class NaraMarketCrawler:
    def __init__(self):
        self.base_url = "https://www.g2b.go.kr"
        self.session = requests.Session()
        self.default_headers = {
            'Content-Type': 'application/json;charset=UTF-8',
            'Origin': 'https://www.g2b.go.kr',
            'Referer': 'https://www.g2b.go.kr/'
        }
        self.search_keywords = [
            "VR", "AR", "실감", "가상현실", "증강현실", "혼합현실", "XR", 
            "메타버스", "LMS", "학습관리시스템", "콘텐츠 개발", "콘텐츠 제작",
            "교재 개발", "교육과정 개발", "교육 콘텐츠"
        ]
        
    async def initialize_session(self):
        """세션 초기화 및 기본 설정"""
        logger.info("세션 초기화 시작")
        try:
            url = f"{self.base_url}/co/coz/coza/util/getSession.do"
            headers = {
                **self.default_headers,
                'menu-info': '{"menuNo":"01175","menuCangVal":"PNPE001_01","bsneClsfCd":"%EC%97%85130026","scrnNo":"00941"}'
            }
            
            response = self.session.post(url, headers=headers)
            response.raise_for_status()
            
            session_data = response.json()
            logger.info(f"세션 초기화 성공: {json.dumps(session_data, indent=2, ensure_ascii=False)}")
            return True
            
        except Exception as e:
            logger.error(f"세션 초기화 실패: {str(e)}")
            return False

    async def search_bids(self, keyword: str, page: int = 1) -> Dict:
        """키워드로 입찰 공고 검색"""
        logger.info(f"검색 시작 - 키워드: {keyword}, 페이지: {page}")
        
        try:
            # 날짜 범위 설정 (한달)
            today = datetime.now()
            month_ago = today - timedelta(days=30)
            
            url = f"{self.base_url}/pn/pnp/pnpe/BidPbac/selectBidPbacScrollTypeList.do"
            headers = {
                **self.default_headers,
                'menu-info': '{"menuNo":"01175","menuCangVal":"PNPE001_01","bsneClsfCd":"%EC%97%85130026","scrnNo":"00941"}'
            }
            
            payload = {
                "dlBidPbancLstM": {
                    "bidPbancNm": keyword,
                    "fromBidDt": month_ago.strftime("%Y%m%d"),
                    "toBidDt": today.strftime("%Y%m%d"),
                    "currentPage": str(page),
                    "recordCountPerPage": "10",
                    "startIndex": (page-1)*10 + 1,
                    "endIndex": page*10,
                    "prcmBsneSeCd": "0000 조070001 조070002 조070003 조070004 조070005 민079999",
                    "pbancKndCd": "공440002"
                }
            }
            
            logger.debug(f"검색 요청 - URL: {url}")
            logger.debug(f"검색 Payload: {json.dumps(payload, indent=2, ensure_ascii=False)}")
            
            response = self.session.post(url, headers=headers, json=payload)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"검색 결과 - 총 {len(data.get('result', []))}건 검색됨")
            return data
            
        except Exception as e:
            logger.error(f"검색 실패 - 키워드: {keyword}, 오류: {str(e)}")
            return {}

    async def get_bid_detail(self, bid_number: str) -> Dict:
        """입찰 공고 상세 정보 조회"""
        logger.info(f"상세 정보 조회 시작 - 공고번호: {bid_number}")
        
        try:
            url = f"{self.base_url}/pn/pnp/pnpe/commBidPbac/selectPicInfo.do"
            headers = {
                **self.default_headers,
                'menu-info': '{"menuNo":"01196","menuCangVal":"PNPE027_01","bsneClsfCd":"%EC%97%85130026","scrnNo":"06085"}'
            }
            
            payload = {
                "dlParamM": {
                    "bidPbancNo": bid_number,
                    "bidPbancOrd": "000"
                }
            }
            
            logger.debug(f"상세 정보 요청 - URL: {url}")
            logger.debug(f"상세 정보 Payload: {json.dumps(payload, indent=2, ensure_ascii=False)}")
            
            response = self.session.post(url, headers=headers, json=payload)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"상세 정보 조회 성공 - 공고번호: {bid_number}")
            return data
            
        except Exception as e:
            logger.error(f"상세 정보 조회 실패 - 공고번호: {bid_number}, 오류: {str(e)}")
            return {}

    async def process_single_keyword(self, keyword: str, max_pages: int = 3):
        """단일 키워드에 대한 처리"""
        logger.info(f"\n{'='*50}\n키워드 처리 시작: {keyword}\n{'='*50}")
        
        results = []
        for page in range(1, max_pages + 1):
            search_results = await self.search_bids(keyword, page)
            
            if not search_results.get('result'):
                logger.info(f"더 이상의 검색 결과 없음 - 키워드: {keyword}, 페이지: {page}")
                break
                
            for item in search_results.get('result', []):
                try:
                    bid_number = item.get('bidPbancNo')
                    if not bid_number:
                        continue
                        
                    logger.info(f"\n{'='*30}\n공고 처리 시작: {bid_number}\n{'='*30}")
                    
                    # 기본 정보 로깅
                    logger.info(f"공고명: {item.get('bidPbancNm')}")
                    logger.info(f"발주기관: {item.get('dmstNm')}")
                    logger.info(f"입찰방식: {item.get('scsbdMthdNm')}")
                    
                    # 상세 정보 조회
                    detail_info = await self.get_bid_detail(bid_number)
                    
                    # 결과 저장
                    bid_info = {
                        'keyword': keyword,
                        'basic_info': item,
                        'detail_info': detail_info
                    }
                    results.append(bid_info)
                    
                    # 처리 간격
                    await asyncio.sleep(1)
                    
                except Exception as e:
                    logger.error(f"공고 처리 중 오류 발생 - 공고번호: {bid_number}, 오류: {str(e)}")
                    continue
            
            # 페이지 간격
            await asyncio.sleep(2)
            
        return results

    async def crawl(self):
        """전체 크롤링 프로세스"""
        logger.info("크롤링 프로세스 시작")
        
        try:
            # 세션 초기화
            if not await self.initialize_session():
                logger.error("세션 초기화 실패로 크롤링 중단")
                return
            
            all_results = []
            
            # 키워드별 처리
            for keyword in self.search_keywords:
                try:
                    results = await self.process_single_keyword(keyword)
                    all_results.extend(results)
                    
                    # 키워드 간격
                    await asyncio.sleep(3)
                    
                except Exception as e:
                    logger.error(f"키워드 처리 중 오류 발생 - 키워드: {keyword}, 오류: {str(e)}")
                    continue
            
            # 결과 저장
            self.save_results(all_results)
            
        except Exception as e:
            logger.error(f"크롤링 프로세스 중 오류 발생: {str(e)}")
        finally:
            logger.info("크롤링 프로세스 종료")

    def save_results(self, results: List[Dict]):
        """결과 저장"""
        try:
            filename = f"crawling_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            logger.info(f"결과 저장 완료: {filename}")
        except Exception as e:
            logger.error(f"결과 저장 실패: {str(e)}")

async def main():
    crawler = NaraMarketCrawler()
    await crawler.crawl()

if __name__ == "__main__":
    load_dotenv()
    asyncio.run(main())