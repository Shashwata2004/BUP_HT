# GridWise submission information

| Item | Value |
| --- | --- |
| GitHub repository | `https://github.com/Shashwata2004/BUP_HT` (private during the event) |
| Public API base URL | `https://bup-ht.onrender.com` |
| Health endpoint | `GET https://bup-ht.onrender.com/health` |
| Optimization endpoint | `POST https://bup-ht.onrender.com/optimize-energy` |
| Docker image | `ghcr.io/shashwata2004/bup_ht:bup-preli-2026` |
| Docker digest | `sha256:fb6d6d3e5e65520368e317f34716b4c7facdf2fdbca3a7be03f011e8af1cd318` |
| Docker package visibility | Private during the event; make publicly pullable after the deadline for evaluation |
| LLM provider/model | Groq — `openai/gpt-oss-120b` |
| Offline tests | 1,592 passed; 12 explicitly skipped live tests; one upstream warning |
| Official optimizer cases | 10/10, exact organizer-optimal costs |
| Official live Groq cases | 10/10, exact organizer-optimal costs |
| Independent semantic suite | 150/150 notes |
| Final semantic red team | 54/54 notes across 18 requests; zero retries/repairs/failures |
| Deployed official cases | 10/10; p50 1.471 s, p95/max 2.017 s |
| Video URL | Not yet supplied — add the accessible final URL before submission |

The API key is stored only in runtime secret configuration. It does not appear in this document, the repository, or the image. Before organizer evaluation, add the accessible video URL, make the GHCR package pullable, and change the source repository to public only after the official deadline.
