# Online Boutique 测试运行说明

本目录包含 Online Boutique 的自动化功能测试脚本和 JMeter 并发压测计划。

## 文件说明

1. `selenium_checkout_test.py`

   Selenium 自动化功能测试脚本，用于模拟用户完成一次下单流程。

   脚本会依次执行：

   - 打开 Online Boutique 首页
   - 进入商品详情页
   - 选择商品数量
   - 将商品加入购物车
   - 进入购物车页面
   - 填写邮箱、地址、银行卡等结算信息
   - 提交订单
   - 记录每轮测试是否成功、耗时和错误信息

2. `online_boutique_load_test.jmx`

   JMeter 并发压测计划，用于模拟多个用户同时访问 Online Boutique。

   测试计划包含：

   - 访问首页 `/`
   - 访问商品详情页 `/product/OLJCESPC7Z`
   - 提交加入购物车请求 `/cart`
   - 访问购物车页面 `/cart`
   - 提交结算请求 `/cart/checkout`

   默认压测参数：

   - 前端地址：`http://127.0.0.1:57794`
   - 并发线程数：`20`
   - 启动时间：`30` 秒
   - 每个线程循环次数：`10`

3. `requirements.txt`

   Python 依赖文件，目前包含 Selenium。

## 运行 Selenium 自动化下单测试

先安装 Python 依赖：

```powershell
python -m pip install -r requirements.txt
```

运行 3 轮自动化下单测试：

```powershell
python selenium_checkout_test.py --rounds 3
```

如果需要指定前端地址，可以使用 `--base-url`：

```powershell
python selenium_checkout_test.py --base-url http://127.0.0.1:57794 --rounds 3
```

如果不想打开浏览器窗口，可以使用无头模式：

```powershell
python selenium_checkout_test.py --base-url http://127.0.0.1:57794 --rounds 3 --headless
```

运行结束后会生成：

```text
selenium-results.json
```

结果文件中包含每轮测试的时间、目标地址、商品 ID、是否成功、耗时和错误信息。

## 运行 JMeter 并发压测

打开 JMeter，选择：

```text
File -> Open -> online_boutique_load_test.jmx
```

在 Test Plan 的 User Defined Variables 中可以修改：

```text
HOST = 127.0.0.1
PORT = 57794
PROTOCOL = http
THREADS = 20
RAMP_UP = 30
LOOPS = 10
```

点击绿色三角按钮开始运行。

## 使用命令行生成 JMeter HTML 报告

也可以用命令行直接运行 JMeter 并生成 HTML 报告：

```powershell
jmeter -n -t online_boutique_load_test.jmx -JHOST=127.0.0.1 -JPORT=57794 -JTHREADS=20 -JLOOPS=10 -l result.jtl -e -o html-report
```

运行结束后，`html-report` 文件夹中就是 JMeter 生成的性能测试报告。

## 结果说明

Selenium 测试结果主要用于验证前端下单流程是否可用，可以关注：

- 测试是否全部成功
- 每轮下单耗时
- 失败时的错误信息

JMeter 测试结果主要用于观察系统在并发访问下的性能，可以关注：

- 平均响应时间
- 最大响应时间
- 吞吐量
- 错误率
- 各请求接口的响应情况
