// stdin: {"orderData":{...}, "chains":{"ethereum":"ethereum-vm",...}} -> stdout computed orderId
const { getOrderId } = require("@relay-protocol/settlement-sdk");
let s = ""; process.stdin.on("data", d => s += d).on("end", () => {
  const j = JSON.parse(s); process.stdout.write(getOrderId(j.orderData, j.chains));
});
