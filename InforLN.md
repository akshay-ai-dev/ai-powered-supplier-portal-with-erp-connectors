# Infor LN and ION Gateway API: why integration is not possible for our application

Saranya Utkuri, SRS Consulting Inc. | 2 October 2026 | Research brief (2 pages)

## 1. Summary

Integrating our application with Infor LN and fetching its data through the **ION API Gateway is not
possible for us**. Infor LN runs in a private, organization-owned cloud that is reachable only through
that organization's own authenticated URL. An external application must be **registered on the
organization's Infor platform by its administrator** before it receives an API key, and **no public
sandbox or sample API** exists to test against.

## 2. What Infor LN and the ION Gateway are

- **Infor LN** is Infor's manufacturing and supply-chain ERP. The current on-premises release is LN 10.8
  (March 2023). Cloud customers run LN-based CloudSuites on Infor's cloud platform, **Infor OS**.
- **ION** is Infor OS's middleware. Its **API Gateway** is the front door for REST APIs: every external
  call passes through it and must carry an OAuth 2.0 bearer token.
- LN offers OData REST services for synchronous calls, BODs through ION for events, and a legacy SOAP
  connector. All of them sit behind the customer's own LN environment.

## 3. How an external application gets access

1. An administrator of the organization (Infor System Administrator, IFS Application Admin or ION API
   Administrator) logs in to **that organization's** Infor OS portal.
2. In API Gateway, under Authorized Apps, the administrator registers our application as a "Backend
   Service" and creates a service account.
3. The administrator downloads the credentials as an `.ionapi` file: client ID and secret, service account
   keys and the organization's token endpoint. This file is the "API key".
4. Our application would request a token (about 2 hours by default) and call LN routes with
   `Authorization: Bearer <token>`. An LN administrator must also authorize each route, or calls fail
   with 403.

Infor's own SDK repository states it directly: "The administrator of the Infor ION API gateway will
create the service account in IFS and register your application."

## 4. Why it will not work for us

| Reason | What the documents show |
| --- | --- |
| Private cloud, organization-level URL | Endpoints contain the organization's tenant name, for example `https://mingle.inforcloudsuite.com:443/ACME_Org/as/` in a partner's Infor ION API setup guide. For LN in the cloud, Infor says connections go over HTTPS to the customer's LN UI server. There is no public endpoint to call. |
| Authentication on every step | Calls need an OAuth 2.0 token. Infor's customer resources, support and documentation portal (Infor Concierge) states "Login required". |
| Registration on their platform | Only the organization's administrator can register an app and issue the `.ionapi` file. We cannot self-register. |
| No sample or sandbox API | Infor's developer portal offers documentation and tutorials, not a public LN API to try. An Infor Community answer says developer sandboxes are available to the partner network, need a paid subscription and come without test data. |
| Cost and licensing unknown | Infor publishes no LN prices, and public sources do not say whether ION API access is included in a customer's license. |

## 5. Conclusion

A live Infor LN connection depends on access that belongs to a customer organization: its private URL,
its administrator's approval and its credentials file. None of these can be obtained from public
sources, and there is no public sandbox to substitute. **The integration will not work out for our
application.** It could only be revisited if an Infor customer or partner provides a non-production
tenant, a read-only service account and its `.ionapi` file.

## 6. Resources

- Infor documentation: [Create an ION API authorized app (LN 10.8)](https://docs.infor.com/ln/10.8/en-us/lnesolh/lnoshybridng/och1699539969137.html),
  [Service authorized app (.ionapi)](https://docs.infor.com/inforos/latest/en-us/useradminlib_cloud/etl_dl_ag/oda1623328668051.html),
  [Authorized app in ION API Gateway](https://docs.infor.com/wfm/2026/en-us/wfmopolh/api_config_on-premise/ebd1696258570654.html),
  [LN multi-tenant cloud access](https://docs.infor.com/ln/2026.x/en-us/lnesolh/lnstudioag/tbh1504268055724.html),
  [LN configuration guide for ION API](https://docs.infor.com/ln/10.7/en-us/lnolh/docs/ln_10.7_widgetsopcnf__en-us.pdf),
  [LN REST API administration](https://docs.infor.com/ln/2025.x/en-us/lnesolh/lnrestapiag/vhc1729609685999.html)
- Infor developer and company pages: [How to call an ION API](https://developer.infor.com/tutorials/api-gateway/how-to-call-an-ion-api),
  [Infor ION API Gateway SDK](https://github.com/infor-cloud/ion-api-sdk),
  [Infor Customer Center and Concierge](https://www.infor.com/customer-center),
  [Developer portal announcement](https://www.prnewswire.com/news-releases/infor-announces-new-developer-portal-and-program-301948082.html),
  Infor RESTful API brochure (supplied)
- Community and partners: [Developer sandbox for Infor cloud ERPs](https://community.infor.com/discussion/35397/is-there-an-easy-way-to-get-a-developer-sandbox-for-the-cloud-saas-erps),
  [ION API permissions](https://community.infor.com/discussion/665/user-account-permissions-to-use-ion-api/p1),
  [Novacura: ION API file](https://docs.novacura.com/flow-connect/working-with-connect/connect-to-systems/connectors/rest/infor-m3-rest/configure-rest-connector-with-ion-api-file)
