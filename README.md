# 🌟 BI Agent: RAG + Few-Shot Performance Comparison

To demonstrate the power of our core **RAG (Retrieval-Augmented Generation)** and **Few-Shot (Knowledge Base)** mechanisms, we tested the BI Agent against a complex **4-table JOIN** e-commerce scenario.

---

## 📝 Test Case Question

> Calculate the total items and total revenue of **'Accessories'** purchased by **non-VIP users** in each country.
> Only include **paid orders**, and sort by total revenue in **descending order**.

---

## ❌ Before Few-Shot: Hallucination & Query Failure

With only **Schema RAG** enabled but lacking business context, the 7B local LLM took shortcuts and hallucinated columns, resulting in an invalid SQL query.

```sql
-- ❌ Failed SQL Generation
SELECT 
    country,
    SUM(CASE WHEN is_vip = 0 AND category = 'Accessories' THEN 1 ELSE 0 END) AS total_items,
    SUM(CASE WHEN is_vip = 0 AND category = 'Accessories' THEN price ELSE 0 END) AS total_amount
FROM orders
JOIN users ON orders.user_id = users.id
WHERE paid_at IS NOT NULL 
  AND is_vip = 0 
  AND category = 'Accessories'
GROUP BY country
ORDER BY total_amount DESC;
```

### 🚨 Failure Analysis

* Missed critical joins to `products` and `order_items`
* Incorrectly assumed `category` and `price` exist in `orders` or `users`
* Demonstrates **schema-level RAG is insufficient without business semantics**

---

## ✅ After Few-Shot: Perfect Generation & Reasoning

After injecting a correct query pattern into the **pgvector knowledge base** via the `/system/add-example` endpoint, the LLM successfully generalized the 4-table JOIN logic.

```sql
-- ✅ Successful SQL Generation
SELECT 
    u.country,
    SUM(oi.quantity) AS total_items,
    SUM(p.price * oi.quantity) AS total_amount
FROM users u
JOIN orders o ON u.id = o.user_id
JOIN order_items oi ON o.id = oi.order_id
JOIN products p ON oi.product_id = p.id
WHERE u.is_vip = FALSE
  AND o.status = 'paid'
  AND p.category = 'Accessories'
GROUP BY u.country
ORDER BY total_amount DESC;
```

---

## 🎯 Key Highlights

* **Perfect JOINs**
  Correctly modeled relationships:
  `users → orders → order_items → products`

* **Smart Aggregation**
  Dynamically computed revenue using:
  `price × quantity`

* **Logical Generalization**
  The model **learned patterns**, not just memorized examples

---

## 🧠 Takeaway

Few-shot learning significantly enhances **schema understanding**, **join reasoning**, and **aggregation correctness**, especially in multi-table analytical queries.
